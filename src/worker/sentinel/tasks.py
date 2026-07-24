import os
import time
import zipfile
from pathlib import Path

from eodag import EODataAccessGateway, EOProduct, setup_logging
from operaton.external_task.external_task import ExternalTask, TaskResult

from worker.common.datasets import sentinel
from worker.common.log_utils import configure_logging, format_duration, format_file_metrics, log_with_context
from worker.common.resources import stac
from worker.common.search_interval import determine_search_interal
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
                    # log_with_context(f"{idx} {scene.properties['id']}", log_context)

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
                        # log_with_context(f"{idx} {scene.properties['id']}", log_context)

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
                log_with_context(
                    f"Downloading {scene['id']} (Destination: {scene_path})",
                    log_context,
                )

                generic_stac_item: dict = self._create_generic_stac_item(scene["id"])
                generic_stac_item["properties"].update(scene)
                eoproduct_scene: EOProduct = EOProduct.from_dict(generic_stac_item)
                scene_path.parent.mkdir(parents=True, exist_ok=True)

                # disable eodag progress bar logging
                setup_logging(verbose=2, no_progress_bar=True)
                dag = EODataAccessGateway()
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
                f"Successfully unzipped {zip_file} to: {output_dir}, {format_duration(time_end - time_start)}",
                log_context,
            )

            # Consider naming convention of zipped/unzipped files
            # Downloaded zip: S2C_MSIL2A_20241122T104401_N0511_R008_T32UMB_20260624T191334.zip
            # Extracted zip: S2C_MSIL2A_20241122T104401_N0511_R008_T32UMB_20260624T191334.SAFE
            scene_folder = os.path.join(output_dir, scene["id"]) + ".SAFE"
            return task.complete(global_variables={"scene_folder": scene_folder})

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
            validity = sentinel.validate_integrity(scene_folder, scene["id"])
        except Exception as e:
            return task.failure(
                error_message="Error checking integrity",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )

        log_with_context(f"Successfully checked integrity for {scene['id']}", log_context)

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
        scene_id = scene["id"]
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

        log_with_context(f"Successfully extracted metadata for {scene['id']}", log_context)

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
