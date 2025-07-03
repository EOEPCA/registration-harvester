# src/worker/tutorial/tasks.py
from flowable.external_worker_client import ExternalJob, JobResult, JobResultBuilder
from pystac_client import Client

from worker.common.log_utils import log_with_context  # For logging
from worker.common.task_handler import TaskHandler


class TutorialDiscoverItemsTaskHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Starting DiscoverItems task ...", log_context)

        try:
            # no input data needed for this task

            # get STAC API url from configuration
            api_url = self.get_config("service_url", "https://stac.dataspace.copernicus.eu/v1/")

            # 2. Perform task logic
            log_with_context(f"Searching STAC items using API: {api_url}", log_context)
            # stac search
            catalog = Client.open(api_url, headers=[])
            search = catalog.search(max_items=100, collections="sentinel-2-l2a", datetime="2025-07-02")
            items = list(search.items_as_dicts())

            # 3. Return success with output variables
            log_with_context("DiscoverItems task completed successfully.", log_context)
            return result.success().variable_string(name="items", value=items)

        except Exception as e:
            error_msg = str(e)
            log_with_context(error_msg, log_context, "error")
            # Use the task_failure helper for consistent error reporting
            return self.task_failure("Error in TutorialDiscoverItemsTaskHandler", error_msg, result)


class TutorialProcessItemTaskHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Starting ProcessItem task ...", log_context)

        try:
            # 1. Get input variables
            item = job.get_variable("item")

            if not item:
                log_with_context("Missing 'item' input variable.", log_context, "error")
                return result.failure().error_message("Input data is missing.")

            # 2. Perform task logic: just logging the item
            log_with_context(f"Processing item {item}", log_context)

            # 3. Return success, no output variable produced by this task
            log_with_context("ProcessItem task completed successfully.", log_context)
            return result.success()

        except Exception as e:
            error_msg = str(e)
            log_with_context(error_msg, log_context, "error")
            # Use the task_failure helper for consistent error reporting
            return self.task_failure("Error in TutorialProcessItemTaskHandler", error_msg, result)
