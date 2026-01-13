import os
from urllib.parse import urlparse, urlunparse

import fsspec
import pystac_client
from eodm.extract import extract_stac_api_collections
from eodm.load import load_stac_api_collections, load_stac_api_items
from eodm.stac_contrib import FSSpecStacIO
from httpx import HTTPStatusError
from pystac import Catalog, Collection, Item, StacIO

from worker.common.log_utils import configure_logging, log_with_context
from worker.common.task_handler import TaskHandler
from worker.common.types import ExternalJob, JobResult, JobResultBuilder

configure_logging()


class StacCatalogHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
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
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # Get the STAC catalog URI
        stac_catalog_source = job.get_variable("stac_catalog_source")
        if not stac_catalog_source:
            log_with_context("Missing required variable: stac_catalog_source", log_context)
            return result.failure()

        stac_catalog_collections = job.get_variable("stac_catalog_collections")
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
                        stac_collection_source = []
                        for collection in extract_stac_api_collections(stac_catalog_source):
                            if collection.id in collections_to_harvest:
                                log_with_context(f"Processing collection {collection.id}", log_context)
                                stac_collection_source.append(collection.get_self_href())
                            else:
                                log_with_context(f"Ignoring collection {collection.id}", log_context)

                    except pystac_client.errors.ClientTypeError as e:
                        # Handle collections
                        parsed = urlparse(stac_catalog_source)
                        comps = parsed.path.strip("/").split("/")
                        stac_type = comps[-2]

                        if stac_type == "collections":
                            return result.success().variable_json(
                                name="stac_collection_source", value=[stac_catalog_source]
                            )
                        else:
                            raise e
                    except Exception:
                        StacIO.set_default(FSSpecStacIO)
                        catalog = Catalog.from_file(stac_catalog_source)
                        stac_collection_source = [
                            collection.get_self_href() for collection in catalog.get_all_collections()
                        ]

                # Handle local files paths (or any other non‑URL string)
                case file_value if file_value.startswith("/"):
                    StacIO.set_default(FSSpecStacIO)
                    catalog = Catalog.from_file(stac_catalog_source)
                    stac_collection_source = [
                        collection.get_self_href() for collection in catalog.get_all_collections()
                    ]

                # Handle S3
                case s3_value if s3_value.startswith("s3://"):
                    # Get optional S3 variables
                    s3_endpoint_url = job.get_variable("s3_endpoint_url")
                    s3_access_key = job.get_variable("s3_access_key")
                    s3_secret_key = job.get_variable("s3_secret_key")
                    if not s3_endpoint_url or not s3_access_key or not s3_secret_key:
                        raise ValueError("Missing required S3 variables: s3_endpoint_url, s3_access_key, s3_secret_key")

                    fs = fsspec.filesystem(
                        "s3", client_kwargs={"endpoint_url": s3_endpoint_url}, key=s3_access_key, secret=s3_secret_key
                    )
                    StacIO.set_default(lambda: FSSpecStacIO(filesystem=fs))

                    catalog = Catalog.from_file(stac_catalog_source)
                    stac_collection_source = [
                        collection.get_self_href() for collection in catalog.get_all_collections()
                    ]

                # Default
                case _:
                    log_with_context(
                        f"Error loading catalog: Could not handle source {stac_catalog_source}", log_context
                    )
                    return result.failure()

        except Exception as e:
            log_with_context(f"Error loading catalog: {str(e)}", log_context)
            return result.failure()

        log_with_context(
            f"Loaded catalog. Starting {len(stac_collection_source)} StacCollectionHandler tasks.", log_context
        )
        return result.success().variable_json(name="stac_collection_source", value=stac_collection_source)


class StacCollectionHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
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
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # Get and validate job variables
        stac_collection_source = job.get_variable("stac_collection_source")
        if not stac_collection_source:
            raise ValueError("Missing required variable: stac_collection_source")
        stac_update_collections = True
        stac_update_collections_param = job.get_variable("stac_update_collections")
        if stac_update_collections_param is not None:
            if isinstance(stac_update_collections_param, str):
                stac_update_collections = stac_update_collections_param.lower() == "true"
            else:
                stac_update_collections = stac_update_collections_param

        # Get and validate required configuration values
        url = self.get_config("stac_api_url", "")
        auth = (self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None))
        if not url:
            raise ValueError("Missing required configuration: stac_api_url")
        if not auth[0] or not auth[1]:
            auth = None

        # Retrieve collection
        try:
            log_with_context(f"Loading STAC collection from: {stac_collection_source}", log_context)
            match stac_collection_source:
                # HTTP/HTTPS URLs - try STAC API first, fall back to plain HTTP/HTTPS
                case url_value if url_value.startswith(("http://", "https://")):
                    try:
                        parsed = urlparse(stac_collection_source)
                        comps = parsed.path.strip("/").split("/")

                        if len(comps) < 2:
                            raise ValueError("Not enough path components in URL")

                        collection_name = comps[-1]
                        catalog_path = "/" + "/".join(comps[:-2])

                        catalog_url = urlunparse(parsed._replace(path=catalog_path))

                        client = pystac_client.Client.open(catalog_url)
                        collection = client.get_collection(collection_name)

                    except Exception:
                        StacIO.set_default(FSSpecStacIO)
                        collection = Collection.from_file(stac_collection_source)

                # Handle local files paths (or any other non‑URL string)
                case file_value if file_value.startswith("/"):
                    StacIO.set_default(FSSpecStacIO)
                    collection = Collection.from_file(stac_collection_source)

                # Handle S3
                case s3_value if s3_value.startswith("s3://"):
                    # Get optional S3 variables
                    s3_endpoint_url = job.get_variable("s3_endpoint_url")
                    s3_access_key = job.get_variable("s3_access_key")
                    s3_secret_key = job.get_variable("s3_secret_key")
                    if not s3_endpoint_url or not s3_access_key or not s3_secret_key:
                        raise ValueError("Missing required S3 variables: s3_endpoint_url, s3_access_key, s3_secret_key")

                    fs = fsspec.filesystem(
                        "s3", client_kwargs={"endpoint_url": s3_endpoint_url}, key=s3_access_key, secret=s3_secret_key
                    )
                    StacIO.set_default(lambda: FSSpecStacIO(filesystem=fs))

                    collection = Collection.from_file(stac_collection_source)

                # Default
                case _:
                    log_with_context(
                        f"Error loading collection: Could not handle source {stac_collection_source}", log_context
                    )
                    return result.failure()

        except Exception as e:
            log_with_context(f"Error loading catalog: {str(e)}", log_context)
            return result.failure()

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
            if e.response.status_code == 409:
                log_with_context(
                    f"Collection {collection.id} already exists. "
                    + "To update this resource set process variable stac_update_collections to true"
                )
        except Exception as e:
            log_with_context(f"Error publishing collection: {str(e)}", log_context)
            return result.failure()

        # log_with_context(f"Collection items: {[item for item in collection.get_items(recursive= True)]}", log_context)

        stac_item_source = [item.get_self_href() for item in collection.get_all_items()]
        log_with_context(
            f"Published collection {collection.id}. Starting {len(stac_item_source)} StacItemHandler tasks.",
            log_context,
        )
        return result.success().variable_json(name="stac_item_source", value=stac_item_source)


class StacItemHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
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
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # Get and validate job variables
        stac_item_source = job.get_variable("stac_item_source")
        if not stac_item_source:
            raise ValueError("Missing required variable: stac_item_source")
        stac_update_items = True
        stac_update_items_param = job.get_variable("stac_update_items")
        if stac_update_items_param is not None:
            if isinstance(stac_update_items_param, str):
                stac_update_items = stac_update_items_param.lower() == "true"
            else:
                stac_update_items = stac_update_items_param

        # Get and validate required configuration values
        url = self.get_config("stac_api_url", "")
        auth = (self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None))
        if not url:
            raise ValueError("Missing required configuration: stac_api_url")
        if not auth[0] or not auth[1]:
            auth = None

        # Retrieve item
        try:
            log_with_context(f"Loading STAC item from: {stac_item_source}", log_context)
            match stac_item_source:
                # HTTP/HTTPS URLs - try STAC API first, fall back to plain HTTP/HTTPS
                case url_value if url_value.startswith(("http://", "https://")):
                    try:
                        parsed = urlparse(stac_item_source)
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
                        item = Item.from_file(stac_item_source)

                # Handle local files paths (or any other non‑URL string)
                case file_value if file_value.startswith("/"):
                    StacIO.set_default(FSSpecStacIO)
                    item = Item.from_file(stac_item_source)

                # Handle S3
                case s3_value if s3_value.startswith("s3://"):
                    # Get optional S3 variables
                    s3_endpoint_url = job.get_variable("s3_endpoint_url")
                    s3_access_key = job.get_variable("s3_access_key")
                    s3_secret_key = job.get_variable("s3_secret_key")
                    if not s3_endpoint_url or not s3_access_key or not s3_secret_key:
                        raise ValueError("Missing required S3 variables: s3_endpoint_url, s3_access_key, s3_secret_key")

                    fs = fsspec.filesystem(
                        "s3", client_kwargs={"endpoint_url": s3_endpoint_url}, key=s3_access_key, secret=s3_secret_key
                    )
                    StacIO.set_default(lambda: FSSpecStacIO(filesystem=fs))

                    item = Item.from_file(stac_item_source)

                # Default
                case _:
                    log_with_context(
                        f"Error loading collection: Could not handle source {stac_item_source}", log_context
                    )
                    return result.failure()

        except Exception as e:
            log_with_context(f"Error loading item: {str(e)}", log_context)
            return result.failure()

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
            if e.response.status_code == 409:
                log_with_context(
                    f"Item {item.id} already exists. "
                    + "To update this resource set process variable stac_update_items to true"
                )
        except Exception as e:
            log_with_context(f"Error publishing item: {str(e)}", log_context)
            return result.failure()

        log_with_context(f"Finished publishing item {item.id}", log_context)
        return result.success()
