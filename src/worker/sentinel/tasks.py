import os
import time
import zipfile
from pathlib import Path

from eodag import EODataAccessGateway, EOProduct, setup_logging
from operaton.external_task.external_task import ExternalTask, TaskResult
from opentelemetry import trace, metrics
from opentelemetry.trace import StatusCode

from worker.common.datasets import sentinel
from worker.common.log_utils import configure_logging, format_duration, format_file_metrics, log_with_context
from worker.common.resources import stac
from worker.common.search_interval import determine_search_interal
from worker.common.task_handler import TaskHandler

configure_logging()

# dotenv for credentials for demo setup only
from dotenv import load_dotenv
load_dotenv()

# Get the tracer/meter for this module/class
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

scenes_found = meter.create_histogram(
    "demo__scenes_found_count", unit="1",
    description="Number of scenes found per discovery run",
)

# Metric Definitions, Module Level
download_bytes = meter.create_histogram(
    "demo__scene_download_bytes", unit="By",
    description="Size of downloaded Sentinel files",
)

download_duration = meter.create_histogram(
    "demo__scene_download_duration_seconds", unit="s",
    description="Duration of the download process itself (excluding cache hits)",
)

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

        # SUBSPAN 1: Parameter Parsing and Validation
        with tracer.start_as_current_span("parse_and_validate_inputs") as span:
            param_collections = task.get_variable("collections")
            param_datetime_interval = task.get_variable("datetime_interval")
            param_bbox = task.get_variable("bbox")

            collections = (
                param_collections.split(",") if param_collections is not None and len(param_collections) > 0 else None
            )
            bbox = param_bbox.split(",") if param_bbox is not None and len(param_bbox) > 0 else None

            if param_datetime_interval:
                start_time, end_time = param_datetime_interval.split("/")
            else:
                start_time, end_time = None, None

            page_size = self.get_config("page_size", 1000)

            if collections is None:
                # Document errors in the Span
                span.set_status(StatusCode.ERROR, "Missing input variable 'collections'")

                log_context["error_details"] = f"Process input variable 'collections' is mandatory and must have a non-empty value"
                log_with_context(f"Missing input variable", log_context, log_level="error")

                return task.failure(
                    error_message="Missing input variable",
                    error_details="Process input variable 'collections' is mandatory and must have a non-empty value",
                    max_retries=0,
                    retry_timeout=0,
                )

        scene_essentials = []

        try:
            dag = EODataAccessGateway()

            # SUBSPAN 2: The API Search (EODAG)
            with tracer.start_as_current_span("eodag_search_all") as search_span:
                # Attributes Help with Filtering in Jaeger/Grafana
                search_span.set_attribute("collections.count", len(collections))

                for collection in collections:
                    # Optional: A separate subspan for each collection, if there are many
                    with tracer.start_as_current_span(f"search_collection_{collection}"):
                        scenes = dag.search_all(
                            provider="cop_dataspace",
                            collection=collection,
                            bbox=bbox,
                            published_after=start_time,
                            published_before=end_time,
                            limit=page_size,
                        )

                        log_with_context(f"Number of scenes found: {len(scenes)}", log_context)

                        # set scenes count for each collection separately
                        scenes_found.record(
                            len(scenes),
                            attributes={"topic_name": task.get_topic_name(), "collection": collection},
                        )

                        # SUBSPAN 3: Data Processing / Data Transformation
                        with tracer.start_as_current_span("process_scene_properties") as proc_span:
                            proc_span.set_attribute("scenes.count", len(scenes))

                            for idx, scene in enumerate(scenes, 1):
                                property_keys_template: list[str] = [
                                    "uid",
                                    "usgs:productId",
                                    "usgs:entityId",
                                    "eodag:download_link",
                                ]

                                payload: dict = {
                                    key: scene.properties.get(key) for key in property_keys_template if
                                    key in scene.properties
                                }

                                payload["eodag:provider"] = scene.provider
                                payload["id"] = scene.properties["id"]
                                scene_essentials.append(payload)
                                if idx == 3:
                                    break  # for testing just three scenes

                            if len(scene_essentials) != len(scenes):
                                current_span = trace.get_current_span()

                                # Register a warning as an event
                                current_span.add_event(
                                    name="warning",
                                    attributes={
                                        "warning.message": f"Only {len(scene_essentials)} of {len(scenes)} scenes were processed",
                                        "warning.type": "PartialProcessingWarning",
                                        "processed_count": len(scene_essentials),
                                        "total_count": len(scenes),
                                        "missing_count": len(scenes) - len(scene_essentials)
                                    }
                                )

                                log_context["error_details"] = f"Only {len(scene_essentials)} of {len(scenes)} scenes were processed"
                                log_with_context(f"Data mismatch", log_context, log_level="warning")


        except Exception as e:
            # Catch exceptions in the currently active root span
            current_span = trace.get_current_span()
            current_span.record_exception(e)
            current_span.set_status(StatusCode.ERROR, str(e))

            log_context["error_details"] = str(e)
            log_with_context(f"Error occurred searching scenes", log_context, log_level="error")

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

        # SUBSPAN 1: Path Calculation and Cache/Existence Check
        with tracer.start_as_current_span("prepare_download_metadata") as prep_span:
            if scene and "id" in scene:
                prep_span.set_attribute("scene.id", scene["id"])

            # TODO: Calculate scene path according to
            # https://gitlab.dlr.de/terrabyte/data-management/ingestion/terrabyte-ingestion-lib/-/blob/main/
            # terrabyte/ingestion/providers/esa_cdse.py#L241-251
            scene_path = Path(self._get_scene_path(self.get_config("download_base_dir", "/tmp"), scene))
            download_retry_wait_time_minutes = self.get_config("download_retry_wait_time_minutes", 0.2)
            download_retry_timeout_minutes = self.get_config("download_retry_timeout_minutes", 10)

            file_exists = os.path.exists(scene_path)
            prep_span.set_attribute("file.exists_in_cache", file_exists)
            prep_span.set_attribute("file.destination_path", str(scene_path))

        if file_exists:
            log_with_context(f"Skipped download. File {scene_path} already exists", log_context)
        else:
            try:
                log_with_context(
                    f"Downloading {scene['id']} (Destination: {scene_path})",
                    log_context,
                )

                # SUBSPAN 2: STAC / EOProduct Preparation
                with tracer.start_as_current_span("build_eoproduct_metadata"):
                    generic_stac_item: dict = self._create_generic_stac_item(scene["id"])
                    generic_stac_item["properties"].update(scene)
                    eoproduct_scene: EOProduct = EOProduct.from_dict(generic_stac_item)
                    scene_path.parent.mkdir(parents=True, exist_ok=True)

                # SUBSPAN 3: The actual network download (I/O-intensive)
                with tracer.start_as_current_span("eodag_download_file") as download_span:
                    download_span.set_attribute("download.timeout_minutes", download_retry_timeout_minutes)
                    download_span.set_attribute("download.retry_wait_minutes", download_retry_wait_time_minutes)

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
                # Log errors in the current root span (or subspan)
                current_span = trace.get_current_span()
                current_span.record_exception(e)
                current_span.set_status(StatusCode.ERROR, str(e))

                log_context["error_details"] = str(e)
                log_with_context(f"Download failed for {scene['id']}", log_context, log_level="error")

                return task.failure(
                    error_message="Download failed",
                    error_details=f"Download failed for {scene['id']}: {str(e)}",
                    max_retries=3,
                    retry_timeout=TaskHandler.TIMEOUT_1_MINUTE,
                )

            time_end = time.perf_counter()
            file_size = scene_path.stat().st_size
            duration = time_end - time_start

            # Record as a metric (in addition to existing logging)
            download_bytes.record(file_size, attributes={"topic_name": task.get_topic_name()})
            download_duration.record(duration, attributes={"topic_name": task.get_topic_name()})

            log_with_context(
                f"Downloaded {scene_path} ({format_file_metrics(scene_path.stat().st_size, time_end - time_start)})",
                log_context,
            )

        # SUBSPAN 4: Post-Processing / Finalization
        with tracer.start_as_current_span("finalize_download_task") as final_span:
            collection = sentinel.get_collection_name(scene["id"])
            final_span.set_attribute("scene.collection_name", str(collection))

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

        # SUBSPAN 1: Parameter-Validation
        with tracer.start_as_current_span("unzip_validate_inputs") as validate_span:
            zip_file = task.get_variable("zip_file")
            scene = task.get_variable("scene")
            remove_zip = self.get_config("remove_zip", False)
            log_with_context(f"Input variables: {zip_file=}", log_context)

            if zip_file:
                validate_span.set_attribute("file.zip_path", zip_file)
            if scene and "id" in scene:
                validate_span.set_attribute("scene.id", scene["id"])

            if not zip_file or not os.path.exists(zip_file) or not zip_file.endswith(".zip"):
                validate_span.set_status(StatusCode.ERROR, "Invalid or missing ZIP file path")

                log_context["error_details"] = f"Path to the downloaded zip file is missing or invalid zip file"
                log_with_context(f"Invalid input for {scene['id']}", log_context, log_level="error")

                return task.failure(
                    error_message="Invalid input",
                    error_details="Path to the downloaded zip file is missing or invalid zip file",
                    max_retries=0,
                    retry_timeout=0,
                )

        try:
            output_dir = os.path.dirname(zip_file)

            # SUBSPAN 2: Hard Disk I/O (Extraction)
            with tracer.start_as_current_span("unzip_extract_archive") as extract_span:
                extract_span.set_attribute("file.output_directory", output_dir)

                with zipfile.ZipFile(zip_file, "r") as zip_ref:
                    extract_span.set_attribute("file.zipped_files_count", len(zip_ref.namelist()))
                    zip_ref.extractall(output_dir)

            # SUBSPAN 3: Cleanup (Optional File Deletion)
            if remove_zip:
                with tracer.start_as_current_span("unzip_remove_source_zip"):
                    os.remove(zip_file)

            time_end = time.perf_counter()
            log_with_context(
                f"Successfully unzipped {zip_file} to: {output_dir}, {format_duration(time_end - time_start)}",
                log_context,
            )

            # SUBSPAN 4: Task Completion and Path Generation
            with tracer.start_as_current_span("unzip_finalize_task") as final_span:
                scene_folder = os.path.join(output_dir, scene["id"]) + ".SAFE"
                final_span.set_attribute("file.extracted_scene_folder", scene_folder)
                return task.complete(global_variables={"scene_folder": scene_folder})

        except zipfile.BadZipFile as e:
            current_span = trace.get_current_span()
            current_span.record_exception(e)
            current_span.set_status(StatusCode.ERROR, f"Bad ZIP file: {str(e)}")

            log_context["error_details"] = f"Invalid zip file {zip_file}: {str(e)}"
            log_with_context(f"An Exception occurred for {scene['id']}", log_context, log_level="error")

            return task.failure(
                error_message="Invalid zip file",
                error_details=f"Invalid zip file {zip_file}: {str(e)}",
                max_retries=0,
                retry_timeout=0,
            )
        except Exception as e:
            current_span = trace.get_current_span()
            current_span.record_exception(e)
            current_span.set_status(StatusCode.ERROR, str(e))

            log_context["error_details"] =f"Error extracting zip file {zip_file}: {str(e)}"
            log_with_context(f"An Exception occurred for {scene['id']}", log_context, log_level="error")

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

        # SUBSPAN 1: Input-Validation
        with tracer.start_as_current_span("integrity_validate_inputs") as validate_span:
            scene = task.get_variable("scene")
            scene_folder = task.get_variable("scene_folder")
            log_with_context(f"Input variables: {scene_folder=}", log_context)

            if scene_folder:
                validate_span.set_attribute("file.scene_folder", scene_folder)
            if scene and "id" in scene:
                validate_span.set_attribute("scene.id", scene["id"])

            if not scene_folder or not os.path.exists(scene_folder):
                validate_span.set_status(StatusCode.ERROR, "Scene folder missing or does not exist")
                log_context["error_details"] = "Scene folder missing or does not exist"
                log_with_context(f"An Exception occurred for {scene['id']}", log_context, log_level="error")
                return task.failure(
                    error_message="Missing or invalid input variable",
                    error_details=f"The variable scene_folder is missing or path {scene_folder} does not exist",
                    max_retries=0,
                    retry_timeout=0,
                )

        try:
            # SUBSPAN 2: Actual Integrity Check
            with tracer.start_as_current_span("integrity_run_validation") as check_span:
                validity = sentinel.validate_integrity(scene_folder, scene["id"])
                check_span.set_attribute("integrity.is_valid", validity)

        except Exception as e:
            current_span = trace.get_current_span()
            current_span.record_exception(e)
            current_span.set_status(StatusCode.ERROR, str(e))

            log_context["error_details"] = str(e)
            log_with_context(f"An Exception occurred for {scene['id']}", log_context, log_level="error")

            return task.failure(
                error_message="Error checking integrity",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )

        # SUBSPAN 3: Task-completion
        with tracer.start_as_current_span("integrity_finalize_task"):
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
            return task.complete()

        except Exception as e:
            return task.failure(
                error_message="Error registering metadata",
                error_details=f"Error registering metadata: {str(e)} at URL {str(api_url)}",
                max_retries=0,
                retry_timeout=0,
            )
