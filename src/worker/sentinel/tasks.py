import os
import time
import zipfile
from pathlib import Path

import requests
from eodag import EODataAccessGateway, EOProduct
from operaton.external_task.external_task import ExternalTask, TaskResult

from worker.common.datasets import sentinel
from worker.common.log_utils import configure_logging, format_duration, format_file_metrics, log_with_context
from worker.common.resources import stac
from worker.common.search_interval import determine_search_interal
from worker.common.secrets import worker_secrets
from worker.common.task_handler import TaskHandler

configure_logging()


class SentinelDiscoverHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Searches for new Sentinel data

        Variables needed:
            collection(s)?

        Variables set:
            scenes: List of scenes found
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        log_with_context("Discovering new Sentinel data ...", log_context)

        # Process variables
        param_collections = task.get_variable("collections")
        param_datetime_interval = task.get_variable("datetime_interval")
        param_bbox = task.get_variable("bbox")

        collections = (
            param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
        )
        bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

        start_time, end_time = param_datetime_interval.split("/")

        page_size = self.get_config("page_size", 1000)

        if collections is None:
            return task.failure(
                error_message="Missing input variable",
                error_details="Process input variable 'collections' is mandatory and must have a non-empty value",
                max_retries=0,
                retry_timeout=0,
            )

        scene_essentials = []

        try:
            dag = EODataAccessGateway()
            for collection in collections:
                scenes = dag.search_all(
                    provider="cop_dataspace",
                    collection=collection,
                    bbox=bbox,
                    published_after=start_time,
                    published_before=end_time,
                    limit=page_size,
                )

                log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                for idx, scene in enumerate(scenes, 1):
                    log_with_context(f"{idx} {scene.properties['id']}", log_context)

                    # Strip scenes to essentials
                    property_keys_template: list[str] = [
                        "uid",
                        "usgs:productId",
                        "usgs:entityId",
                        "eodag:download_link",
                    ]

                    payload: dict = {
                        key: scene.properties.get(key) for key in property_keys_template if key in scene.properties
                    }

                    payload["eodag:provider"] = scene.provider
                    payload["id"] = scene.properties["id"]
                    scene_essentials.append(payload)

        except Exception as e:
            return task.failure(
                error_message="Error searching scenes",
                error_details=repr(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
            )

        return task.complete(global_variables={"scenes": scene_essentials})


class SentinelContinuousDiscoveryHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Searches for new Sentinel data continuously

        Variables needed:

        Variables set:
            scenes: List of scenes found
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        scene_essentials = []

        if self.get_config("enabled", False):
            log_with_context("Continuous discovery of new Sentinel data ...", log_context)

            # Handle config input
            page_size = self.get_config("page_size", 1000)
            timewindow_hours = self.get_config("timewindow_hours", 1)
            start_time, end_time = determine_search_interal(task, timewindow_hours)
            param_collections = self.get_config("collections", "")
            collections = (
                param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
            )
            param_bbox = self.get_config("bbox", "")
            bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

            try:
                dag = EODataAccessGateway()
                for collection in collections:
                    scenes = dag.search_all(
                        provider="cop_dataspace",
                        collection=collection,
                        bbox=bbox,
                        published_after=start_time,
                        published_before=end_time,
                        limit=page_size,
                    )

                    log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                    for idx, scene in enumerate(scenes, 1):
                        log_with_context(f"{idx} {scene.properties['id']}", log_context)

                        # Strip scenes to essentials
                        property_keys_template: list[str] = [
                            "uid",
                            "usgs:productId",
                            "usgs:entityId",
                            "eodag:download_link",
                        ]
                        payload: dict = {
                            key: scene.properties.get(key) for key in property_keys_template if key in scene.properties
                        }
                        payload["eodag:provider"] = scene.provider
                        payload["id"] = scene.properties["id"]
                        scene_essentials.append(payload)

            except Exception as e:
                return task.failure(
                    error_message="Error searching scenes",
                    error_details=repr(e),
                    max_retries=3,
                    retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
                )
        else:
            log_with_context("Continuous discovery is disabled by configuration, skipping ...", log_context)

        return task.complete(global_variables={"scenes": scene_essentials})


class SentinelDownloadHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        time_start = time.perf_counter()

        scene = task.get_variable("scene")
        log_with_context(f"Input variables: {scene=}", context=log_context, log_level="debug")

        # TODO: Calculate scene path according to
        # https://gitlab.dlr.de/terrabyte/data-management/ingestion/terrabyte-ingestion-lib/-/blob/main/
        # terrabyte/ingestion/providers/esa_cdse.py#L241-251
        scene_path = Path(self._get_scene_path(self.get_config("download_base_dir", "/tmp"), scene))
        download_retry_wait_time_minutes = self.get_config("download_retry_wait_time_minutes", 0.2)
        download_retry_timeout_minutes = self.get_config("download_retry_timeout_minutes", 10)

        if os.path.exists(scene_path):
            log_with_context(f"Skipped download. File {scene_path} already exists", log_context)
        else:
            try:
                generic_stac_item: dict = self._create_generic_stac_item(scene["id"])
                generic_stac_item["properties"].update(scene)

                eoproduct_scene: EOProduct = EOProduct.from_dict(generic_stac_item)

                dag = EODataAccessGateway()

                scene_path.parent.mkdir(parents=True, exist_ok=True)
                log_with_context(
                    f"Downloading {scene['id']} (Destination: {scene_path})",
                    log_context,
                )
                dag.download(
                    product=eoproduct_scene,
                    extract=False,
                    output_dir=str(scene_path.parent),
                    wait=download_retry_wait_time_minutes,
                    timeout=download_retry_timeout_minutes,
                )

            except Exception as e:
                return task.failure(
                    error_message="Download failed",
                    error_details=f"Download failed for {scene['id']}: {str(e)}",
                    max_retries=3,
                    retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
                )

            time_end = time.perf_counter()
            log_with_context(
                f"Downloaded {scene_path} ({format_file_metrics(scene_path.stat().st_size, time_end - time_start)})",
                log_context,
            )

        collection = sentinel.get_collection_name(scene["id"])
        log_with_context(f"{collection=}")
        return task.complete(global_variables={"zip_file": str(scene_path), "collection": str(collection)})

    def _get_scene_path(self, base_dir, scene):
        zip_path = Path(scene["id"].lstrip("/") + ".zip")
        return str(Path(base_dir) / zip_path)

    def _get_access_token(self):
        if "token_expire_time" in os.environ and time.time() <= (float(os.environ["token_expire_time"]) - 5):
            return os.environ["s3_access_key"]

        cdse_user = worker_secrets.get_secret("cdse_user", "")
        cdse_password = worker_secrets.get_secret("cdse_password", "")
        auth_server_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        data = {
            "client_id": "cdse-public",
            "grant_type": "password",
            "username": cdse_user,
            "password": cdse_password,
        }

        token_time = time.time()
        response = requests.post(auth_server_url, data=data, verify=True, allow_redirects=False).json()
        os.environ["token_expire_time"] = str(token_time + response.get("expires_in", 0))
        os.environ["s3_access_key"] = response.get("access_token", "")
        return os.environ["s3_access_key"]

    def _download_data(
        self,
        url,
        output_dir,
        file_name=None,
        chunk_size=1024 * 1000,
        timeout=300,
        auth=None,
        check_size=True,
        overwrite=False,
    ):
        """
        Download single file from USGS M2M by download url
        """

        if auth:
            r = requests.get(url, stream=True, allow_redirects=True, timeout=timeout, auth=auth)
        else:
            r = requests.get(url, stream=True, allow_redirects=True, timeout=timeout)
        r.raise_for_status()

        expected_file_size = int(r.headers.get("content-length", -1))
        if file_name is None:
            try:
                file_name = r.headers["Content-Disposition"].split('"')[1]
            except Exception:
                file_name = os.path.basename(url)
                # raise Exception("Can not automatically identify file_name.")

        file_path = os.path.join(output_dir, file_name)
        # TODO: Check for existing files and whether they have the correct file size
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        if os.path.exists(file_path) and not overwrite:
            return file_path
        elif os.path.exists(file_path) and overwrite:
            os.remove(file_path)

        with open(file_path, "wb") as f:
            # start = time.perf_counter()
            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)
            # duration = time.perf_counter() - start

        file_size = os.stat(file_path).st_size
        # speed = round((file_size / duration) / (1000 * 1000), 2)

        if check_size:
            if expected_file_size != file_size:
                os.remove(file_path)
                raise Exception(f"Failed to download from {url}")

        return file_path

    @staticmethod
    def _create_generic_stac_item(_id: str) -> dict:
        return {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": f"{_id}",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {
                "title": f"{_id}",
                "eodag:search_intersection": {"type": "Polygon", "coordinates": [[]]},
            },
        }


class SentinelUnzipHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Unzips the downloaded Sentinel data file.

        Variables needed:
            zip_file: Path to the downloaded zip file

        Variables set:
            scene_folder: Path to the unzipped scene folder
        """
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }
        time_start = time.perf_counter()

        # get job variables
        zip_file = task.get_variable("zip_file")
        scene = task.get_variable("scene")
        remove_zip = self.get_config("remove_zip", False)
        log_with_context(f"Input variables: {zip_file=}", log_context)

        if not zip_file or not os.path.exists(zip_file) or not zip_file.endswith(".zip"):
            return task.failure(
                error_message="Invalid input",
                error_details="Path to the downloaded zip file is missing or invalid zip file",
                max_retries=0,
                retry_timeout=0,
            )

        try:
            # Create the output directory (same as zip file but without .zip extension)
            output_dir = os.path.dirname(zip_file)

            with zipfile.ZipFile(zip_file, "r") as zip_ref:
                zip_ref.extractall(output_dir)

            if remove_zip:
                os.remove(zip_file)

            time_end = time.perf_counter()
            log_with_context(
                f"Successfully unzipped {scene['scene_id']} to: {output_dir}, {format_duration(time_end - time_start)}",
                log_context,
            )

            return task.complete(global_variables={"scene_folder": os.path.join(output_dir, scene["scene_id"])})

        except zipfile.BadZipFile as e:
            return task.failure(
                error_message="Invalid zip file",
                error_details=f"Invalid zip file {zip_file}: {str(e)}",
                max_retries=0,
                retry_timeout=0,
            )
        except Exception as e:
            return task.failure(
                error_message="Error extracting zip file",
                error_details=f"Error extracting zip file {zip_file}: {str(e)}",
                max_retries=0,
                retry_timeout=0,
            )


class SentinelCheckIntegrityHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        # get job variables
        scene = task.get_variable("scene")
        scene_folder = task.get_variable("scene_folder")
        log_with_context(f"Input variables: {scene_folder=}", log_context)

        if not scene_folder or not os.path.exists(scene_folder):
            return task.failure(
                error_message="Missing or invalid input variable",
                error_details=f"The variable scene_folder is missing or path {scene_folder} does not exist",
                max_retries=0,
                retry_timeout=0,
            )

        try:
            validity = sentinel.validate_integrity(scene_folder, scene["scene_id"])
        except Exception as e:
            return task.failure(
                error_message="Error checking integrity",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )

        log_with_context(f"Successfully checked integrity for {scene['scene_id']}", log_context)

        return task.complete(global_variables={"validity": validity})


class SentinelExtractMetadataHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        # get job variables
        scene = task.get_variable("scene")
        scene_id = scene["scene_id"]
        scene_folder = task.get_variable("scene_folder")
        collections_dir = self.get_config("collections_dir", os.path.dirname(__file__))
        log_with_context(f"Input variables: {scene_folder=}, {scene_id=}", log_context)

        if not scene_folder or not os.path.exists(scene_folder) or not scene_id or not scene:
            return task.failure(
                error_message="Missing or invalid inputs",
                error_details=f"scene_folder, scene_id or scene are missing or {scene_folder} does not exist",
                max_retries=0,
                retry_timeout=0,
            )

        try:
            stac_item = sentinel.create_metadata(
                scene_path=scene_folder, scene_id=scene_id, collections_dir=collections_dir
            )
        except Exception as e:
            return task.failure(
                error_message="Error extracting metadata",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )

        log_with_context(f"Successfully extracted metadata for {scene['scene_id']}", log_context)

        return task.complete(global_variables={"stac_item": str(stac_item)})


class SentinelRegisterMetadataHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        # get config
        api_url = self.get_config("stac_api_url", "")
        api_user = self.get_config("stac_api_user", None)
        api_pw = self.get_config("stac_api_pw", None)
        api_ca_cert = self.get_config("stac_api_ca_cert", None)
        file_deletion = self.get_config("stac_file_deletion", True)

        # Asset href rewriting
        rewrite_asset_hrefs = self.get_config("rewrite_asset_hrefs", None)

        # get job variables
        scene = task.get_variable("scene")
        collection = task.get_variable("collection")
        stac_item = task.get_variable("stac_item")
        log_with_context(f"Input variables: {scene=}, {collection=}", log_context)

        if not scene or not collection or not stac_item:
            return task.failure(
                error_message="Missing input variables",
                error_details="The variables scene, collection or stac_item are missing",
                max_retries=0,
                retry_timeout=0,
            )

        try:
            token = None
            if self.iam_client is not None:
                # Get token to access protected endpoints of catalog
                token = self.iam_client.get_access_token()

            stac.register_metadata(
                stac_file=stac_item,
                collection=collection,
                api_url=api_url,
                api_user=api_user,
                api_pw=api_pw,
                api_token=token,
                api_ca_cert=api_ca_cert,
                file_deletion=file_deletion,
                rewrite_asset_hrefs=rewrite_asset_hrefs,
            )
            task.complete()
        except Exception as e:
            return task.failure(
                error_message="Error registering metadata",
                error_details=f"Error registering metadata: {str(e)} at URL {str(api_url)}",
                max_retries=0,
                retry_timeout=0,
            )
