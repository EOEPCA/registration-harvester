import datetime
import json
import os

from dateutil.parser import parse

from worker.common.base.file import untar_file
from worker.common.client import flowable_client
from worker.common.datasets import landsat
from worker.common.log_utils import configure_logging, log_with_context
from worker.common.providers import usgs
from worker.common.resources import stac
from worker.common.task_handler import TaskHandler
from worker.common.types import ExternalJob, JobResult, JobResultBuilder
from worker.landsat.discovery import search

configure_logging()


class LandsatDiscoverHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Searches for new data

        Variables needed:
            collections
            datetime_interval
            bbox
            query

        Variables set:
            scenes: List of scenes found
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Discovering new Landsat data ...", log_context)

        # Configuration
        api_url = self.get_config("usgs_api_url", "https://landsatlook.usgs.gov/stac-server")
        page_size = self.get_config("page_size", 100)

        # Process variables
        param_collections = job.get_variable("collections")
        param_datetime_interval = job.get_variable("datetime_interval")
        param_bbox = job.get_variable("bbox")
        param_query = job.get_variable("query")

        # Discover scenes
        collections = (
            param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
        )
        bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None
        query = json.loads(param_query) if param_query is not None and len(param_query) > 0 else None

        if collections is None:
            error_message = "Process input variable 'collections' is mandatory and must have a non-empty value"
            log_with_context(error_message, log_context, "error")
            # return result.failure().error_message(error_message).retries(0).retry_timeout("PT10M")
            return result.success().variable_json(name="scenes", value=[])

        if param_datetime_interval is None and bbox is None and query is None:
            error_message = (
                "At least one of the input variables datetime_interval, bbox or query must be provided for discovery"
            )
            log_with_context(error_message, log_context, "error")
            # return result.failure().error_message(error_message).retries(0).retry_timeout("PT10M")
            return result.success().variable_json(name="scenes", value=[])

        log_with_context(f"Search parameter: collections={collections}", log_context)
        log_with_context(f"Search parameter: datetime_interval='{param_datetime_interval}'", log_context)
        log_with_context(f"Search parameter: bbox='{bbox}'", log_context)
        log_with_context(f"Search parameter: query='{query}'", log_context)

        try:
            scenes = search(api_url, collections, bbox, param_datetime_interval, page_size, query)
            log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
            for idx, item in enumerate(scenes, 1):
                # log_with_context(json.dumps(item))
                log_with_context(f"{idx} {api_url}/collections/{item["collection"]}/items/{item["id"]}", log_context)

        except Exception as e:
            error_msg = repr(e)
            log_with_context(error_msg, log_context)
            return self.task_failure("Error searching scenes", error_msg, result, retries=3, timeout="PT20M")

        return result.success().variable_json(name="scenes", value=scenes)


class LandsatContinuousDiscoveryHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Searches for new data continuously

        Variables needed:
            collections
            bbox
            timewindow in hours
            datetime property to query

        Variables set:
            scenes: List of scenes found
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

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
            start_time, end_time = self.determine_search_interal(job, timewindow_hours)
            query = json.loads(json.dumps({datetime_property: {"gte": start_time, "lt": end_time}}))

            log_with_context(f"Search parameter: collections={collections}", log_context)
            log_with_context(f"Search parameter: bbox='{bbox}'", log_context)
            log_with_context(f"Search parameter: query='{query}'", log_context)

            try:
                scenes = search(api_url, collections, bbox, None, page_size, query)
                log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                for idx, item in enumerate(scenes, 1):
                    log_with_context(
                        f"{idx} {api_url}/collections/{item["collection"]}/items/{item["id"]}", log_context
                    )

            except Exception as e:
                error_msg = str(e)
                log_with_context(error_msg, log_context)
                return self.task_failure("Error in continous discovery", error_msg, result, retries=3, timeout="PT20M")

        else:
            log_with_context("Continous discovery is disabled by configuration, skipping ...", log_context)
            scenes = []

        return result.success().variable_json(name="scenes", value=scenes)

    def determine_search_interal(self, job: ExternalJob, timedelta_hours: float) -> tuple[str, str]:
        history = flowable_client.get_process_instance_history(job.process_instance_id)
        if "startTime" in history:
            current_time = parse(history["startTime"])
        else:
            current_time = datetime.datetime.now()
        end_time = datetime.datetime(current_time.year, current_time.month, current_time.day, current_time.hour)
        start_time = end_time - datetime.timedelta(hours=timedelta_hours)
        start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return start_time, end_time


class LandsatGetDownloadUrlHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Get download urls for discovered scenes

        Variables needed:
            scenes: List of scenes found

        Variables set:
            scenes: List of scenes found
            urls: List of download urls for scenes
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Get download urls for discovered scenes ...", log_context)

        scenes = job.get_variable("scenes")
        m2m_api_user = self.get_config("m2m_user", "eoepca")
        m2m_api_password = self.get_config("m2m_password", "")
        m2m_api_use_token = self.get_config("m2m_use_token", True)
        m2m_api_url = self.get_config("m2m_api_url", "https://m2m.cr.usgs.gov/api/api/json/stable/")

        try:
            api_key = usgs.login(m2m_api_user, m2m_api_password, m2m_api_use_token, m2m_api_url)
            scenes = usgs.add_download_urls(scenes, api_key)
        except Exception as e:
            error_msg = str(e)
            log_with_context(error_msg, log_context)
            return self.task_failure("Error getting download urls", error_msg, result, retries=3, timeout="PT20M")

        for idx, scene in enumerate(scenes, 1):
            log_with_context(f"{idx} id={scene["id"]} collection={scene["collection"]} url={scene["url"]}", log_context)
            # log_with_context(json.dumps(scene))

        return result.success().variable_json(name="scenes", value=scenes)


class LandsatDownloadHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Downloads a Landsat scene

        Variables needed:
            scene: Current scene

        Variables set:
            scene: Current scene
            scene_downloaded = Boolean
            tar_file = Path to the downloaded tar file
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        scene = job.get_variable("scene")
        if "url" not in scene:
            error_msg = "No URL available in scene variable"
            log_with_context(error_msg, log_context)
            return self.task_failure("Error Downloading Landsat scene", error_msg, result, retries=0)

        download_url = scene["url"]
        log_with_context("Downloading Landsat scene from URL %s" % (download_url), log_context)

        base_dir = self.get_config("download_base_dir", "/tmp")
        download_timeout = self.get_config("download_timeout", 300)
        temp_dir = usgs.get_scene_id_folder(scene["id"])
        download_dir = os.path.join(base_dir, temp_dir)
        file_path = os.path.join(download_dir, f"{scene["id"]}.tar")

        if os.path.exists(file_path):
            log_with_context(f"Skipped download. File {file_path} already exists", log_context)
        else:
            try:
                log_with_context(f"Downloading Landsat scene into directory {download_dir}", log_context)
                file_path = usgs.download_data(url=download_url, output_dir=download_dir, timeout=download_timeout)
            except Exception as e:
                error_msg = repr(e)
                log_with_context(error_msg, log_context)
                return self.task_failure("Download failed", error_msg, result, retries=3, timeout="PT20M")

            if not isinstance(file_path, str) or not os.path.exists(file_path):
                error_msg = f"Downloaded file {file_path} does not exists"
                log_with_context(error_msg, log_context)
                return self.task_failure("Download failed", error_msg, result, retries=3, timeout="PT20M")

        return (
            result.success()
            .variable_boolean(name="scene_downloaded", value=True)
            .variable_string(name="tar_file", value=file_path)
        )


class LandsatUntarHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Extracts the downloaded scene

        Variables needed:
            tar_file = Path to the downloaded tar file

        Variables set:
            scene_path = Path to the untared scene folder
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        tar_file = job.get_variable("tar_file")
        remove_tar = self.get_config("remove_tar", False)
        create_folder = self.get_config("create_folder", True)
        log_with_context(f"Untar downloaded scene {tar_file} ...", log_context)

        if not os.path.exists(tar_file):
            error_msg = f"File does not exist: {tar_file}"
            log_with_context(error_msg, log_context, "error")
            return self.task_failure("Untar failed", error_msg, result, retries=0)

        try:
            (scene_path, tar_file_removed) = untar_file(tar_file, remove_tar=remove_tar, create_folder=create_folder)
        except Exception as e:
            error_msg = str(e)
            log_with_context(error_msg, log_context, "error")
            return self.task_failure("Untar failed", error_msg, result, retries=0)

        return (
            result.success()
            .variable_string(name="scene_path", value=scene_path)
            .variable_boolean(name="tar_file_removed", value=tar_file_removed)
        )


class LandsatExtractMetadataHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Extract STAC metadata

        Variables needed:
            scene: Current scene
            scene_path = Path to the untared scene folder

        Variables set:
            scene_stac_file = Path to the file containing the STAC item for this scene
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        scene_path = job.get_variable("scene_path")
        scene = job.get_variable("scene")
        log_with_context(f"Extracting metadata for {scene_path} ...", log_context)

        if not os.path.exists(scene_path):
            error_msg = f"Scene folder does not exist: {scene_path}"
            log_with_context(error_msg, log_context, "error")
            return self.task_failure("Extracting metadata failed", error_msg, result, retries=0)

        try:
            stac_file = landsat.landsat_metadata(scene_path, scene["id"], False, True)

        except Exception as e:
            error_msg = str(e)
            log_with_context(error_msg, log_context, "error")
            return self.task_failure("Extracting metadata failed", error_msg, result, retries=0)

        return result.success().variable_string(name="scene_stac_file", value=stac_file)


class LandsatRegisterMetadataHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Register metadata at catalog

        Variables needed:
            scene: Current scene
            scene_stac_file = Path to the file containing the STAC item for this scene

        Variables set:
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        scene = job.get_variable("scene")
        scene_stac_file = job.get_variable("scene_stac_file")
        log_with_context(f"Register metadata for item {scene["id"]} and stac file {scene_stac_file} ...", log_context)
        # log_with_context(json.dumps(scene))

        api_url = self.get_config("stac_api_url", "")
        api_user = self.get_config("stac_api_user", None)
        api_pw = self.get_config("stac_api_pw", None)
        api_ca_cert = self.get_config("stac_api_ca_cert", None)
        file_deletion = self.get_config("stac_file_deletion", True)

        # validate input
        vars_not_set = self.validate([scene, scene_stac_file, api_url])
        if len(vars_not_set) > 0:
            return self.task_failure(
                "Job input validation failed", f"Variables {vars_not_set} must not be empty", result, retries=0
            )

        try:
            stac.register_metadata(
                stac_file=scene_stac_file,
                collection=scene["collection"],
                api_url=api_url,
                api_user=api_user,
                api_pw=api_pw,
                api_ca_cert=api_ca_cert,
                file_deletion=file_deletion,
            )
        except Exception as e:
            error_msg = str(e)
            log_with_context(error_msg, log_context, "error")
            return self.task_failure("Register metadata error", error_msg, result)

        log_with_context("Finished.", log_context)
        return result.success()

    def validate(self, job_vars: list):
        return list(filter(lambda v: v is None, job_vars))
