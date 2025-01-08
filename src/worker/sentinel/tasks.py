import datetime

from dateutil.parser import parse
from registration_library.providers import esa_cdse as cdse

from worker.common.client import flowable_client
from worker.common.log_utils import configure_logging, log_with_context
from worker.common.task_handler import TaskHandler
from worker.common.types import ExternalJob, JobResult, JobResultBuilder

configure_logging()


class SentinelDiscoverHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Searches for new data since last workflow execution

        Variables needed:
            start_time
            end_time
            order_id

        Variables set:
            scenes: List of scenes found
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Discovering new sentinel data ...", log_context)

        # Workflow variables
        start_time = job.get_variable("start_time")
        end_time = job.get_variable("end_time")
        order_id = job.get_variable("order_id")
        if order_id is None:
            order_id = job.process_instance_id

        if start_time is None and end_time is None:
            history = flowable_client.get_process_instance_history(job.process_instance_id)
            if "startTime" in history:
                current_time = parse(history["startTime"])  # 2024-03-17T01:02:22.487+0000
                log_with_context("use startTime from workflow: %s" % current_time, log_context)
            else:
                current_time = datetime.datetime.now()
                log_with_context("use datetime.now() as startTime: %s" % current_time, log_context)
            end_time = datetime.datetime(current_time.year, current_time.month, current_time.day, current_time.hour)
            start_time = end_time - datetime.timedelta(hours=1)
            start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        log_with_context(f"Search interval: {start_time} - {end_time}", log_context)

        # Discovering scenes
        try:
            scenes = cdse.search_scenes_ingestion(date_from=start_time, date_to=end_time, filters=None)
        except Exception as e:
            log_with_context(f"Error searching scenes: {e}", log_context)
            return result.error(f"Error searching scenes: {e}")

        return result.success().variable_json(name="scenes", value=scenes)


def sentinel_download_data(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
    log_with_context("Downloading data ...", log_context)

    # get job variables
    log_with_context(job.get_variable("scene"), log_context)

    return result.success()


def sentinel_unzip(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
    log_with_context("Unzipping ...", log_context)

    return result.success()


def sentinel_check_integrity(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
    log_with_context("Checking integrity ...", log_context)

    # get job variables
    scene = job.get_variable("scene")
    log_with_context(f"Input variable: scene={scene}", log_context)

    # scene["collection"] = "sentinel-1"
    scene["collection"] = ""
    log_with_context(f"Output variable: scene={scene}", log_context)

    return (
        result.success()
        .variable_string(name="collection", value=scene["collection"])
        .variable_json(name="scene", value=scene)
    )


def sentinel_extract_metadata(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
    log_with_context("Extracting metadata and creating STAC item ...", log_context)

    # get job variables
    log_with_context(f"scene={job.get_variable("scene")}", log_context)
    log_with_context(f"collection={job.get_variable("collection")}", log_context)

    return result.success()


def sentinel_register_metadata(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
    log_with_context("Registering STAC item ...", log_context)

    # get job variables
    log_with_context(f"scene={job.get_variable("scene")}", log_context)
    log_with_context(f"collection={job.get_variable("collection")}", log_context)

    return result.success()


# tasks_config = {
#     "sentinel_discover_data": {
#         "callback_handler": sentinel_discover_data,
#         "lock_duration": "PT1M",
#         "number_of_retries": 5,
#         "scope_type": None,
#         "wait_period_seconds": 1,
#         "number_of_tasks": 1,
#     },
# "sentinel_download_data": {
#     "callback_handler": sentinel_download_data,
#     "lock_duration": "PT1M",
#     "number_of_retries": 5,
#     "scope_type": None,
#     "wait_period_seconds": 1,
#     "number_of_tasks": 1,
# },

# "sentinel_unzip": {
#     "callback_handler": sentinel_unzip,
#     "lock_duration": "PT1M",
#     "number_of_retries": 5,
#     "scope_type": None,
#     "wait_period_seconds": 1,
#     "number_of_tasks": 1,
# },
# "sentinel_check_integrity": {
#     "callback_handler": sentinel_check_integrity,
#     "lock_duration": "PT1M",
#     "number_of_retries": 5,
#     "scope_type": None,
#     "wait_period_seconds": 1,
#     "number_of_tasks": 1,
# },
# "sentinel_extract_metadata": {
#     "callback_handler": sentinel_extract_metadata,
#     "lock_duration": "PT1M",
#     "number_of_retries": 5,
#     "scope_type": None,
#     "wait_period_seconds": 1,
#     "number_of_tasks": 1,
# },
# "sentinel_register_metadata": {
#     "callback_handler": sentinel_register_metadata,
#     "lock_duration": "PT1M",
#     "number_of_retries": 5,
#     "scope_type": None,
#     "wait_period_seconds": 1,
#     "number_of_tasks": 1,
# },
# }
