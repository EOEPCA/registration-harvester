import json
import os
from pathlib import Path

from operaton.external_task.external_task import ExternalTask, TaskResult
from eodag import EODataAccessGateway, EOProduct

from worker.common.base.file import untar_file
from worker.common.datasets import landsat
from worker.common.log_utils import configure_logging, log_with_context
from worker.common.resources import stac
from worker.common.search_interval import determine_search_interal
from worker.common.task_handler import TaskHandler

configure_logging()


class LandsatDiscoverHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Searches for new Landsat data

        Variables needed:
            collections
            datetime_interval
            bbox
            query

        Variables set:
            scenes: List of scenes found
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        log_with_context("Discovering new Landsat data ...", log_context)

        # Configuration
        page_size = self.get_config("page_size", 100)

        # Process variables
        param_collections = task.get_variable("collections")
        param_datetime_interval = task.get_variable("datetime_interval")
        param_bbox = task.get_variable("bbox")

        # Discover scenes
        collections = (
            param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
        )
        bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

        start_time, end_time = param_datetime_interval.split("/")

        ingest_filter = {"start": start_time, "end": end_time}
        scene_filter_input = {
            "ingestFilter": ingest_filter
        }

        if collections is None:
            return task.failure(
                error_message="Missing input variable",
                error_details="Process input variable 'collections' is mandatory and must have a non-empty value",
                max_retries=0,
                retry_timeout=0,
            )

        if param_datetime_interval is None and bbox is None:
            return task.failure(
                error_message="Missing input variable",
                error_details="One of the input variables datetime_interval, bbox or query must be provided",
                max_retries=0,
                retry_timeout=0,
            )

        log_with_context(f"Search parameter: collections={collections}", log_context)
        log_with_context(f"Search parameter: datetime_interval='{param_datetime_interval}'", log_context)
        log_with_context(f"Search parameter: bbox='{bbox}'", log_context)

        scene_essentials = []

        try:
            dag = EODataAccessGateway()
            for collection in collections:
                scenes = dag.search_all(
                    provider="usgs",
                    collection=collection,
                    bbox=bbox,
                    limit=page_size,
                    scene_filter=scene_filter_input,
                )

                log_with_context(f"Number of scenes found: {len(scenes)}", log_context)

                for idx, scene in enumerate(scenes, 1):
                    log_with_context(f"{idx} {scene.properties['id']}", log_context)

                    # Strip scenes to essentials
                    property_keys_template: list[str] = ["uid", "usgs:productId", "usgs:entityId",
                                                         "eodag:download_link"]
                    payload: dict = {key: scene.properties.get(key)
                                     for key in property_keys_template
                                     if key in scene.properties}
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


class LandsatContinuousDiscoveryHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Searches for new Landsat data continuously

        Variables needed:
            collections
            bbox
            timewindow in hours
            datetime property to query

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
            log_with_context("Continuous discovery of new Landsat data ...", log_context)

            # Handle input variables
            page_size = self.get_config("page_size", 100)
            param_collections = self.get_config("collections", "")
            collections = (
                param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
            )
            param_bbox = self.get_config("bbox", "")
            bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

            # Create query for time window
            timewindow_hours = self.get_config("timewindow_hours", 1)
            start_time, end_time = determine_search_interal(task, timewindow_hours)

            ingest_filter = {"start": start_time, "end": end_time}
            scene_filter_input = {
                "ingestFilter": ingest_filter
            }

            log_with_context(f"Search parameter: collections={collections}", log_context)
            log_with_context(f"Search parameter: bbox='{bbox}'", log_context)

            try:
                dag = EODataAccessGateway()
                for collection in collections:
                    scenes = dag.search_all(
                        provider="usgs",
                        collection=collection,
                        bbox=bbox,
                        limit=page_size,
                        scene_filter=scene_filter_input,
                    )

                    log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                    for idx, scene in enumerate(scenes, 1):
                        log_with_context(f"{idx} {scene.properties["id"]}", log_context)

                        # Strip scenes to essentials
                        property_keys_template: list[str] = ["uid", "usgs:productId", "usgs:entityId",
                                                             "eodag:download_link"]
                        payload: dict = {key: scene.properties.get(key)
                                         for key in property_keys_template
                                         if key in scene.properties}
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
            log_with_context("Continous discovery is disabled by configuration, skipping ...", log_context)

        return task.complete(global_variables={"scenes": scene_essentials})


class LandsatDownloadHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Downloads a Landsat scene

        Variables needed:
            scene: Current scene

        Variables set:
            scene: Current scene
            scene_downloaded = Boolean
            tar_file = Path to the downloaded tar file
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        scene = task.get_variable("scene")

        log_with_context("Downloading scene %s" % (scene['id']), log_context)

        base_dir = self.get_config("download_base_dir", "/tmp")
        temp_dir = landsat.get_scene_id_folder(scene["id"])
        download_dir = os.path.join(base_dir, temp_dir)
        file_path = str(os.path.join(download_dir, f"{scene['id']}.tar.gz"))

        if os.path.exists(file_path):
            log_with_context(f"Skipped download. File {file_path} already exists", log_context)
        else:
            try:
                log_with_context(f"Downloading scene into directory {download_dir}", log_context)

                generic_stac_item: dict = self._create_generic_stac_item(scene["id"])
                generic_stac_item["properties"].update(scene)

                eoproduct_scene: EOProduct = EOProduct.from_dict(generic_stac_item)

                dag = EODataAccessGateway()

                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
                paths = dag.download(
                    product=eoproduct_scene,
                    extract=False,
                    output_dir=Path(file_path).parent,
                    timeout=10 # 10min is eodag default
                )

            except Exception as e:
                return task.failure(
                    error_message="Download failed",
                    error_details=repr(e),
                    max_retries=3,
                    retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
                )

            if not isinstance(file_path, str) or not os.path.exists(file_path):
                return task.failure(
                    error_message="Download failed",
                    error_details=f"Downloaded file {file_path} does not exists",
                    max_retries=3,
                    retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
                )

        return task.complete(global_variables={"scene_downloaded": True, "tar_file": file_path})

    @staticmethod
    def _create_generic_stac_item(_id: str) -> dict:
        return {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": f"{_id}",
            "geometry": {
                "type": "Point",
                "coordinates": [0, 0]
            },
            "properties": {
                "title": f"{_id}",
                "eodag:search_intersection": {
                    "type": "Polygon",
                    "coordinates": [[
                    ]]
                },
            },
        }


class LandsatUntarHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Extracts the downloaded scene

        Variables needed:
            tar_file = Path to the downloaded tar file

        Variables set:
            scene_path = Path to the untared scene folder
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        tar_file = task.get_variable("tar_file")
        remove_tar = self.get_config("remove_tar", False)
        create_folder = self.get_config("create_folder", True)
        log_with_context(f"Untar downloaded scene {tar_file} ...", log_context)

        if not os.path.exists(tar_file):
            return task.failure(
                error_message="Untar failed",
                error_details=f"File does not exist: {tar_file}",
                max_retries=0,
                retry_timeout=0,
            )

        try:
            scene_path, tar_file_removed = untar_file(tar_file, remove_tar=remove_tar, create_folder=create_folder)
        except Exception as e:
            return task.failure(
                error_message="Untar failed",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
            )

        return task.complete(global_variables={"scene_path": scene_path, "tar_file_removed": tar_file_removed})


class LandsatExtractMetadataHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Extract STAC metadata

        Variables needed:
            scene: Current scene
            scene_path = Path to the untared scene folder

        Variables set:
            scene_stac_file = Path to the file containing the STAC item for this scene
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        scene_path = task.get_variable("scene_path")
        scene = task.get_variable("scene")
        log_with_context(f"Extracting metadata for {scene_path} ...", log_context)

        if not os.path.exists(scene_path):
            return task.failure(
                error_message="Extracting metadata failed",
                error_details=f"Scene folder does not exist: {scene_path}",
                max_retries=0,
                retry_timeout=0,
            )

        try:
            stac_file = landsat.landsat_metadata(scene_path, scene["id"], False, True)

        except Exception as e:
            return task.failure(
                error_message="Extracting metadata failed",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )

        return task.complete(global_variables={"scene_stac_file": stac_file})


class LandsatRegisterMetadataHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        """
        Register metadata at catalog

        Variables needed:
            scene: Current scene
            scene_stac_file = Path to the file containing the STAC item for this scene

        Variables set:
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        scene = task.get_variable("scene")
        scene_stac_file = task.get_variable("scene_stac_file")
        log_with_context(f"Register metadata for item {scene['id']} and stac file {scene_stac_file} ...", log_context)
        # log_with_context(json.dumps(scene))

        api_url = self.get_config("stac_api_url", "")
        api_user = self.get_config("stac_api_user", None)
        api_pw = self.get_config("stac_api_pw", None)
        api_ca_cert = self.get_config("stac_api_ca_cert", None)
        file_deletion = self.get_config("stac_file_deletion", True)

        # Asset href rewriting
        rewrite_asset_hrefs = self.get_config("rewrite_asset_hrefs", None)

        # validate input
        vars_not_set = self.validate([scene, scene_stac_file, api_url])
        if len(vars_not_set) > 0:
            return task.failure(
                error_message="Missing input variable",
                error_details=f"Variables {vars_not_set} must not be empty",
                max_retries=0,
                retry_timeout=0,
            )

        # Get token to access protected endpoints of catalog
        token = self.iam_client.get_access_token()

        try:
            stac.register_metadata(
                stac_file=scene_stac_file,
                collection=scene["collection"],
                api_url=api_url,
                api_user=api_user,
                api_pw=api_pw,
                api_token=token,
                api_ca_cert=api_ca_cert,
                file_deletion=file_deletion,
                rewrite_asset_hrefs=rewrite_asset_hrefs,
            )
        except Exception as e:
            return task.failure(
                error_message="Error register metadata",
                error_details=str(e),
                max_retries=0,
                retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
            )

        log_with_context("Finished.", log_context)
        return task.complete()

    def validate(self, job_vars: list):
        return list(filter(lambda v: v is None, job_vars))
