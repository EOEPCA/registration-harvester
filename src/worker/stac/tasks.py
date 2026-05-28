import os
from urllib.parse import urlparse, urlunparse

import fsspec
import pystac_client
from eodm.extract import extract_stac_api_collections
from eodm.load import load_stac_api_collections, load_stac_api_items
from eodm.stac_contrib import FSSpecStacIO
from httpx import HTTPStatusError
from operaton.external_task.external_task import ExternalTask, TaskResult
from pystac import Catalog, Collection, Item, StacIO

from worker.common.log_utils import configure_logging, log_with_context
from worker.common.search_interval import determine_search_interal
from worker.common.task_handler import TaskHandler

configure_logging()


class StacCatalogHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Load STAC catalog and extract collection paths

        Variables needed:
            stac_catalog_source: URI to the STAC catalog file (can be a local path, HTTP/HTTPS URL, STAC API or S3 URL)
            s3_endpoint_url: (Optional) S3 endpoint URL for custom S3 servers like Minio
            s3_access_key: (Optional) S3 access key
            s3_secret_key: (Optional) S3 secret key

        Variables set:
            stac_collection_source: List of collection URIs (can be local paths, HTTP/HTTPS URLs, or S3 URLs)
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        # Get the STAC catalog URI
        stac_catalog_source = task.get_variable("stac_catalog_source")
        if not stac_catalog_source:
            return task.failure(
                error_message="Missing input variable",
                error_details="The variable stac_catalog_source is missing",
                max_retries=0,
                retry_timeout=0,
            )

        stac_catalog_collections = task.get_variable("stac_catalog_collections")
        if not stac_catalog_collections:
            log_with_context(
                f"No collections provided. All collections from {stac_catalog_source} will be harvested", log_context
            )
        else:
            if len(stac_catalog_collections) > 0:
                collections_to_harvest = stac_catalog_collections.replace(" ", "").split(",")

        try:
            log_with_context(f"Loading STAC catalog from: {stac_catalog_source}", log_context)

            match stac_catalog_source:
                # HTTP/HTTPS URLs - try STAC API first, fall back to plain HTTP/HTTPS
                case url_value if url_value.startswith(("http://", "https://")):
                    try:
                        # Handle STAC APIs
                        StacIO.set_default(FSSpecStacIO)
                        collections = []
                        for collection in extract_stac_api_collections(stac_catalog_source):
                            if collection.id in collections_to_harvest:
                                log_with_context(f"Processing collection {collection.id}", log_context)
                                collections.append(collection.get_self_href())
                            else:
                                log_with_context(f"Ignoring collection {collection.id}", log_context)

                    except pystac_client.errors.ClientTypeError as e:
                        # Handle collections
                        parsed = urlparse(stac_catalog_source)
                        comps = parsed.path.strip("/").split("/")
                        stac_type = comps[-2]

                        if stac_type == "collections":
                            return task.complete(global_variables={"stac_collection_source": [stac_catalog_source]})
                        else:
                            raise e
                    except Exception:
                        StacIO.set_default(FSSpecStacIO)
                        catalog = Catalog.from_file(stac_catalog_source)
                        collections = [collection.get_self_href() for collection in catalog.get_all_collections()]

                # Handle local files paths (or any other non‑URL string)
                case file_value if file_value.startswith("/"):
                    StacIO.set_default(FSSpecStacIO)
                    catalog = Catalog.from_file(stac_catalog_source)
                    collections = [collection.get_self_href() for collection in catalog.get_all_collections()]

                # Handle S3
                case s3_value if s3_value.startswith("s3://"):
                    # Get optional S3 variables
                    s3_endpoint_url = task.get_variable("s3_endpoint_url")
                    s3_access_key = task.get_variable("s3_access_key")
                    s3_secret_key = task.get_variable("s3_secret_key")
                    if not s3_endpoint_url or not s3_access_key or not s3_secret_key:
                        raise ValueError("Missing required S3 variables: s3_endpoint_url, s3_access_key, s3_secret_key")

                    fs = fsspec.filesystem(
                        "s3", client_kwargs={"endpoint_url": s3_endpoint_url}, key=s3_access_key, secret=s3_secret_key
                    )
                    StacIO.set_default(lambda: FSSpecStacIO(filesystem=fs))

                    catalog = Catalog.from_file(stac_catalog_source)
                    collections = [collection.get_self_href() for collection in catalog.get_all_collections()]

                # Default
                case _:
                    return task.failure(
                        error_message="Error loading catalog",
                        error_details=f"Could not handle source {stac_catalog_source}",
                        max_retries=0,
                        retry_timeout=0,
                    )

        except Exception as e:
            return task.failure(
                error_message="Error loading catalog",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )

        log_with_context(f"Loaded catalog. Starting {len(collections)} StacCollectionHandler tasks.", log_context)
        return task.complete(global_variables={"collections": collections})


class StacCollectionHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Publish STAC collection to STAC API

        Variables needed:
            stac_collection_source: URI to the STAC collection file (can be a local path, HTTP/HTTPS URL, or S3 URL)
            s3_endpoint_url: (Optional) S3 endpoint URL for custom S3 servers like Minio
            s3_access_key: (Optional) S3 access key
            s3_secret_key: (Optional) S3 secret key

        Variables set:
            stac_item_source: List of item URIs (can be local paths, HTTP/HTTPS URLs, or S3 URLs)
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        # Get and validate job variables
        collection_param = task.get_variable("collection")
        if not collection_param:
            raise ValueError("Missing required variable: collection")
        stac_update_collections = True
        stac_update_collections_param = task.get_variable("stac_update_collections")
        if stac_update_collections_param is not None:
            if isinstance(stac_update_collections_param, str):
                stac_update_collections = stac_update_collections_param.lower() == "true"
            else:
                stac_update_collections = stac_update_collections_param

        # Get and validate required configuration values
        url = str(self.get_config("stac_api_url", ""))
        if url.endswith("/"):
            url = url[:-1]

        auth = (self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None))
        if not url:
            raise ValueError("Missing required configuration: stac_api_url")
        if not auth[0] or not auth[1]:
            auth = None

        # List of all collection items to load
        items = []

        # Retrieve collection
        try:
            log_with_context(f"Loading STAC collection from: {collection_param}", log_context)
            match collection_param:
                # HTTP/HTTPS URLs - try STAC API first, fall back to plain HTTP/HTTPS
                case url_value if url_value.startswith(("http://", "https://")):
                    try:
                        parsed = urlparse(collection_param)
                        comps = parsed.path.strip("/").split("/")

                        if len(comps) < 2:
                            raise ValueError("Not enough path components in URL")

                        collection_name = comps[-1]
                        catalog_path = "/" + "/".join(comps[:-2])

                        catalog_url = urlunparse(parsed._replace(path=catalog_path))

                        client = pystac_client.Client.open(catalog_url)
                        collection = client.get_collection(collection_name)

                        # avoid getting all items with  collection.get_all_items()
                        # use default filter expression instead, if none is given
                        datetime_interval = task.get_variable("datetime")
                        param_bbox = task.get_variable("bbox")
                        bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

                        if datetime_interval is None:
                            timewindow_hours = self.get_config("timewindow_hours", 1)
                            start_time, end_time = determine_search_interal(task, timewindow_hours)
                            datetime_interval = f"{start_time}/{end_time}"

                        log_with_context("Determine items to harvest from collection ...", log_context)
                        log_with_context(f"datetime_interval='{datetime_interval}' and bbox='{bbox}'", log_context)
                        client = pystac_client.Client.open(catalog_url)
                        search = client.search(
                            collections=[collection_name],
                            datetime=datetime_interval,
                            bbox=bbox,
                            max_items=1000,
                            sortby="+datetime",
                        )
                        items = [item.get_self_href() for item in search.items()]

                    except Exception:
                        StacIO.set_default(FSSpecStacIO)
                        collection = Collection.from_file(collection_param)
                        items = [item.get_self_href() for item in collection.get_all_items()]

                # Handle local files paths (or any other non‑URL string)
                case file_value if file_value.startswith("/"):
                    StacIO.set_default(FSSpecStacIO)
                    collection = Collection.from_file(collection_param)
                    items = [item.get_self_href() for item in collection.get_all_items()]

                # Handle S3
                case s3_value if s3_value.startswith("s3://"):
                    # Get optional S3 variables
                    s3_endpoint_url = task.get_variable("s3_endpoint_url")
                    s3_access_key = task.get_variable("s3_access_key")
                    s3_secret_key = task.get_variable("s3_secret_key")
                    if not s3_endpoint_url or not s3_access_key or not s3_secret_key:
                        raise ValueError("Missing required S3 variables: s3_endpoint_url, s3_access_key, s3_secret_key")

                    fs = fsspec.filesystem(
                        "s3", client_kwargs={"endpoint_url": s3_endpoint_url}, key=s3_access_key, secret=s3_secret_key
                    )
                    StacIO.set_default(lambda: FSSpecStacIO(filesystem=fs))

                    collection = Collection.from_file(collection_param)
                    items = [item.get_self_href() for item in collection.get_all_items()]

                # Default
                case _:
                    return task.failure(
                        error_message="Error loading collection",
                        error_details=f"Could not handle source {collection_param}",
                        max_retries=3,
                        retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
                    )

        except Exception as e:
            return task.failure(
                error_message="Error loading catalog",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )

        # Get token to access protected endpoints of catalog
        token = self.iam_client.get_access_token()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

        # Publish stac collection
        try:
            log_with_context(f"Publishing collection {collection.id} ...", log_context)
            for collection_loaded in load_stac_api_collections(
                url=url,
                collections=[collection],
                headers=headers,
                verify=False,
                update=stac_update_collections,
                auth=None,
            ):
                url = os.path.join(url, "collections", collection_loaded.id)
                log_with_context(f"Successfully published collection at {url}", log_context)
        except HTTPStatusError as e:
            error = str(e)
            if e.response.status_code == 409:
                error = (
                    f"Collection {collection.id} already exists. "
                    + "To update this resource set process variable stac_update_collections to true"
                )
            return task.failure(
                error_message="Error publishing item",
                error_details=error,
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )
        except Exception as e:
            return task.failure(
                error_message="Error publishing collection",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )

        log_with_context(
            f"Published collection {collection.id}. Starting {len(items)} StacItemHandler tasks.",
            log_context,
        )
        # return result.success().variable_json(name="stac_item_source", value=stac_item_source)
        return task.complete(global_variables={"items": items})


class StacItemHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Publish STAC item to STAC API

        Variables needed:
            stac_item_source: URI to the STAC item file (can be a local path, HTTP/HTTPS URL, or S3 URL)
            s3_endpoint_url: (Optional) S3 endpoint URL for custom S3 servers like Minio
            s3_access_key: (Optional) S3 access key
            s3_secret_key: (Optional) S3 secret key

        Variables set:
            None
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        # Get and validate job variables
        item_param = task.get_variable("item")
        if not item_param:
            raise ValueError("Missing required variable: item")
        stac_update_items = True
        stac_update_items_param = task.get_variable("stac_update_items")
        if stac_update_items_param is not None:
            if isinstance(stac_update_items_param, str):
                stac_update_items = stac_update_items_param.lower() == "true"
            else:
                stac_update_items = stac_update_items_param

        # Get and validate required configuration values
        url = str(self.get_config("stac_api_url", ""))
        if url.endswith("/"):
            url = url[:-1]

        auth = (self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None))
        if not url:
            raise ValueError("Missing required configuration: stac_api_url")
        if not auth[0] or not auth[1]:
            auth = None

        # Retrieve item
        try:
            log_with_context(f"Loading STAC item from: {item_param}", log_context)
            match item_param:
                # HTTP/HTTPS URLs - try STAC API first, fall back to plain HTTP/HTTPS
                case url_value if url_value.startswith(("http://", "https://")):
                    try:
                        parsed = urlparse(item_param)
                        comps = parsed.path.strip("/").split("/")

                        if len(comps) < 2:
                            raise ValueError("Not enough path components in URL")

                        collection_name = comps[-3]
                        item_id = comps[-1]
                        catalog_path = "/" + "/".join(comps[:-4])
                        catalog_url = urlunparse(parsed._replace(path=catalog_path))

                        client = pystac_client.Client.open(catalog_url)
                        search = client.search(ids=[item_id], collections=[collection_name])
                        item = [item for item in search.items()][0]
                    except Exception:
                        StacIO.set_default(FSSpecStacIO)
                        item = Item.from_file(item_param)

                # Handle local files paths (or any other non‑URL string)
                case file_value if file_value.startswith("/"):
                    StacIO.set_default(FSSpecStacIO)
                    item = Item.from_file(item_param)

                # Handle S3
                case s3_value if s3_value.startswith("s3://"):
                    # Get optional S3 variables
                    s3_endpoint_url = task.get_variable("s3_endpoint_url")
                    s3_access_key = task.get_variable("s3_access_key")
                    s3_secret_key = task.get_variable("s3_secret_key")
                    if not s3_endpoint_url or not s3_access_key or not s3_secret_key:
                        raise ValueError("Missing required S3 variables: s3_endpoint_url, s3_access_key, s3_secret_key")

                    fs = fsspec.filesystem(
                        "s3", client_kwargs={"endpoint_url": s3_endpoint_url}, key=s3_access_key, secret=s3_secret_key
                    )
                    StacIO.set_default(lambda: FSSpecStacIO(filesystem=fs))

                    item = Item.from_file(item_param)

                # Default
                case _:
                    return task.failure(
                        error_message="Error loading collection",
                        error_details=f"Could not handle item {item_param}",
                        max_retries=0,
                        retry_timeout=0,
                    )

        except Exception as e:
            return task.failure(
                error_message="Error loading item",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )

        # Get token to access protected endpoints of catalog
        token = self.iam_client.get_access_token()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

        # Publish STAC item
        try:
            log_with_context(f"Publishing item {item.id} ...", log_context)
            for item_loaded in load_stac_api_items(
                url=url,
                items=[item],
                headers=headers,
                verify=False,
                update=stac_update_items,
                auth=None,
            ):
                url = os.path.join(url, "collections", item_loaded.collection_id, "items", item_loaded.id)
                log_with_context(f"Successfully published item at {url}", log_context)

        except HTTPStatusError as e:
            error = str(e)
            if e.response.status_code == 409:
                error = (
                    f"Item {item.id} already exists. "
                    + "To update this resource set process variable stac_update_items to true"
                )
            return task.failure(
                error_message="Error publishing item",
                error_details=error,
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )
        except Exception as e:
            return task.failure(
                error_message="Error publishing item",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )

        log_with_context(f"Finished publishing item {item.id}", log_context)
        return task.complete()
