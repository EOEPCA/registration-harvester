import os

import fsspec
from eodm.load import load_stac_api_collections, load_stac_api_items
from eodm.stac_contrib import FSSpecStacIO
from pystac import Catalog, Collection, Item, StacIO

from worker.common.iam import IAMClient
from worker.common.log_utils import configure_logging, log_with_context
from worker.common.secrets import worker_secrets
from worker.common.task_handler import TaskHandler
from worker.common.types import ExternalJob, JobResult, JobResultBuilder

configure_logging()

iam_client_id = worker_secrets.get_secret("iam_client_id")
iam_client_secret = worker_secrets.get_secret("iam_client_secret")
iam_oidc_token_endpoint_url = "https://iam-auth.apx.develop.eoepca.org/realms/eoepca/protocol/openid-connect/token"
iam_client = IAMClient(
    token_endpoint_url=iam_oidc_token_endpoint_url, client_id=iam_client_id, client_secret=iam_client_secret
)


class StacCatalogHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Load STAC catalog and extract collection paths

        Variables needed:
            stac_catalog_source: URI to the STAC catalog file (can be a local path, HTTP/HTTPS URL, or S3 URL)
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

        try:
            log_with_context(f"Loading STAC catalog from: {stac_catalog_source}", log_context)

            # Set up StacIO
            if stac_catalog_source.startswith("s3://"):
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

            else:
                StacIO.set_default(FSSpecStacIO)

            # Read the stac catalog
            catalog = Catalog.from_file(stac_catalog_source)

        except Exception as e:
            log_with_context(f"Error loading catalog: {str(e)}", log_context)
            return result.failure()

        stac_collection_source = [collection.get_self_href() for collection in catalog.get_all_collections()]
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

        # Get and validate required configuration values
        url = self.get_config("stac_api_url", "")
        auth = (self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None))
        if not url:
            raise ValueError("Missing required configuration: stac_api_url")
        if not auth[0] or not auth[1]:
            auth = None

        try:
            log_with_context(f"Loading STAC collection from: {stac_collection_source}", log_context)
            # Set up StacIO
            if stac_collection_source.startswith("s3://"):
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

            else:
                StacIO.set_default(FSSpecStacIO)

            collection = Collection.from_file(stac_collection_source)

        except Exception as e:
            log_with_context(f"Error loading collection: {str(e)}", log_context)
            return result.failure()

        # Get token to access protected endpoints of catalog
        token = iam_client.get_access_token()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

        # Publish stac collection
        try:
            log_with_context(f"Publishing collection {collection.id} ...", log_context)
            for collection_loaded in load_stac_api_collections(
                url=url,
                collections=[collection],
                headers=headers,
                verify=False,
                update=True,
                auth=None,
            ):
                url = os.path.join(url, "collections", collection_loaded.id)
                log_with_context(f"Successfully published collection at {url}", log_context)

        except Exception as e:
            log_with_context(f"Error publishing collection: {str(e)}", log_context)
            return result.failure()

        stac_item_source = [item.get_self_href() for item in collection.get_all_items()]
        log_with_context(
            f"Published collection {collection.id}. " f"Starting {len(stac_item_source)} StacItemHandler tasks.",
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

        # Get and validate required configuration values
        url = self.get_config("stac_api_url", "")
        auth = (self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None))
        if not url:
            raise ValueError("Missing required configuration: stac_api_url")
        if not auth[0] or not auth[1]:
            auth = None

        try:
            log_with_context(f"Loading STAC item from: {stac_item_source}", log_context)
            # Set up StacIO
            if stac_item_source.startswith("s3://"):
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

            else:
                StacIO.set_default(FSSpecStacIO)

            item = Item.from_file(stac_item_source)

        except Exception as e:
            log_with_context(f"Error loading item: {str(e)}", log_context)
            return result.failure()

        # Get token to access protected endpoints of catalog
        token = iam_client.get_access_token()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

        # Publish STAC item
        try:
            log_with_context(f"Publishing item {item.id} ...", log_context)
            for item_loaded in load_stac_api_items(
                url=url,
                items=[item],
                headers=headers,
                verify=False,
                update=True,
                auth=None,
            ):
                url = os.path.join(url, "collections", item_loaded.collection_id, "items", item_loaded.id)
                log_with_context(f"Successfully published item at {url}", log_context)

        except Exception as e:
            log_with_context(f"Error publishing item: {str(e)}", log_context)
            return result.failure()

        log_with_context(f"Finished publishing item {item.id}", log_context)
        return result.success()
