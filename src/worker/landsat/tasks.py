import json
import os

from operaton.external_task.external_task import ExternalTask, TaskResult

from worker.common.base.file import untar_file
from worker.common.datasets import landsat
from worker.common.log_utils import configure_logging, log_with_context
from worker.common.providers import usgs
from worker.common.resources import stac
from worker.common.search_interval import determine_search_interal
from worker.common.secrets import worker_secrets
from worker.common.task_handler import TaskHandler
from worker.landsat.discovery import search

configure_logging()


class LandsatDiscoverHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
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
        api_url = self.get_config("usgs_api_url", "https://landsatlook.usgs.gov/stac-server")
        page_size = self.get_config("page_size", 100)

        # Process variables
        param_collections = task.get_variable("collections")
        param_datetime_interval = task.get_variable("datetime_interval")
        param_bbox = task.get_variable("bbox")
        param_query = task.get_variable("query")

        # Discover scenes
        collections = (
            param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
        )
        bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None
        query = json.loads(param_query) if param_query is not None and len(param_query) > 0 else None

        if collections is None:
            return task.failure(
                error_message="Missing input variable",
                error_details="Process input variable 'collections' is mandatory and must have a non-empty value",
                max_retries=0,
                retry_timeout=0,
            )

        if param_datetime_interval is None and bbox is None and query is None:
            return task.failure(
                error_message="Missing input variable",
                error_details="One of the input variables datetime_interval, bbox or query must be provided",
                max_retries=0,
                retry_timeout=0,
            )

        log_with_context(f"Search parameter: collections={collections}", log_context)
        log_with_context(f"Search parameter: datetime_interval='{param_datetime_interval}'", log_context)
        log_with_context(f"Search parameter: bbox='{bbox}'", log_context)
        log_with_context(f"Search parameter: query='{query}'", log_context)

        try:
            scenes = search(api_url, collections, bbox, param_datetime_interval, page_size, query)
            log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
            for idx, item in enumerate(scenes, 1):
                # log_with_context(json.dumps(item))
                log_with_context(f"{idx} {api_url}/collections/{item['collection']}/items/{item['id']}", log_context)

        except Exception as e:
            return task.failure(
                error_message="Error searching scenes",
                error_details=repr(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
            )

        return task.complete(global_variables={"scenes": scenes})


class LandsatContinuousDiscoveryHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
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

        if self.get_config("enabled", False):
            log_with_context("Continous discovery of new Landsat data ...", log_context)

            # Handle input variables
            api_url = self.get_config("usgs_api_url", "https://landsatlook.usgs.gov/stac-server")
            page_size = self.get_config("page_size", 100)
            param_collections = self.get_config("collections", "")
            collections = (
                param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
            )
            param_bbox = self.get_config("bbox", "")
            bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

            # Create query for time window
            timewindow_hours = self.get_config("timewindow_hours", 1)
            datetime_property = self.get_config("datetime_property", "created")
            start_time, end_time = determine_search_interal(task, timewindow_hours)
            query = json.loads(json.dumps({datetime_property: {"gte": start_time, "lt": end_time}}))

            log_with_context(f"Search parameter: collections={collections}", log_context)
            log_with_context(f"Search parameter: bbox='{bbox}'", log_context)
            log_with_context(f"Search parameter: query='{query}'", log_context)

            try:
                scenes = search(api_url, collections, bbox, None, page_size, query)
                log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                for idx, item in enumerate(scenes, 1):
                    log_with_context(
                        f"{idx} {api_url}/collections/{item['collection']}/items/{item['id']}", log_context
                    )

            except Exception as e:
                return task.failure(
                    error_message="Error searching scenes",
                    error_details=repr(e),
                    max_retries=3,
                    retry_timeout=TaskHandler.TIMEOUT_5_MINUTES,
                )

        else:
            log_with_context("Continous discovery is disabled by configuration, skipping ...", log_context)
            scenes = []

        return task.complete(global_variables={"scenes": scenes})


class LandsatGetDownloadUrlHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
        """
        Get download urls for discovered scenes

        Variables needed:
            scenes: List of scenes found

        Variables set:
            scenes: List of scenes found
            urls: List of download urls for scenes
        """

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }

        log_with_context("Get download urls for discovered scenes ...", log_context)

        scenes = task.get_variable("scenes")
        m2m_api_user = worker_secrets.get_secret("m2m_user", "")
        m2m_api_password = worker_secrets.get_secret("m2m_password", "")
        m2m_api_use_token = self.get_config("m2m_use_token", True)
        m2m_api_url = self.get_config("m2m_api_url", "https://m2m.cr.usgs.gov/api/api/json/stable/")

        try:
            api_key = usgs.login(m2m_api_user, m2m_api_password, m2m_api_use_token, m2m_api_url)
            scenes = usgs.add_download_urls(scenes, api_key)
        except Exception as e:
            return task.failure(
                error_message="Error getting download urls",
                error_details=str(e),
                max_retries=3,
                retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
            )

        for idx, scene in enumerate(scenes, 1):
            log_with_context(f"{idx} id={scene['id']} collection={scene['collection']} url={scene['url']}", log_context)
            # log_with_context(json.dumps(scene))

        return task.complete(global_variables={"scenes": scenes})


class LandsatDownloadHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
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
        if "url" not in scene:
            return task.failure(
                error_message="Error downloading scene",
                error_details="No URL available in scene variable",
                max_retries=0,
                retry_timeout=0,
            )

        download_url = scene["url"]
        log_with_context("Downloading scene from URL %s" % (download_url), log_context)

        base_dir = self.get_config("download_base_dir", "/tmp")
        download_timeout = self.get_config("download_timeout", 300)
        temp_dir = landsat.get_scene_id_folder(scene["id"])
        download_dir = os.path.join(base_dir, temp_dir)
        file_path = os.path.join(download_dir, f"{scene['id']}.tar")

        if os.path.exists(file_path):
            log_with_context(f"Skipped download. File {file_path} already exists", log_context)
        else:
            try:
                log_with_context(f"Downloading scene into directory {download_dir}", log_context)
                file_path = usgs.download_data(url=download_url, output_dir=download_dir, timeout=download_timeout)
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


class LandsatUntarHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
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
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
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
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
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
