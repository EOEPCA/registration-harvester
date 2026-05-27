# src/worker/tutorial/tasks.py
from operaton.external_task.external_task import ExternalTask, TaskResult
from pystac_client import Client

from worker.common.log_utils import log_with_context  # For logging
from worker.common.task_handler import TaskHandler


class TutorialDiscoverItemsTaskHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }
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
            return task.complete(global_variables={"items": items})

        except Exception as e:
            return task.failure(
                error_message="Error in TutorialDiscoverItemsTaskHandler",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )


class TutorialProcessItemTaskHandler(TaskHandler):
    def execute(self, task: ExternalTask, config: dict) -> TaskResult:
        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": task.get_topic_name(),
        }
        log_with_context("Starting ProcessItem task ...", log_context)

        try:
            # 1. Get input variables
            item = task.get_variable("item")

            if not item:
                return task.failure(
                    error_message="Missing input variable",
                    error_details="The variable 'item' is missing",
                    max_retries=0,
                    retry_timeout=0,
                )

            # 2. Perform task logic: just logging the item
            log_with_context(f"Processing item {item}", log_context)

            # 3. Return success, no output variable produced by this task
            log_with_context("ProcessItem task completed successfully.", log_context)
            return task.complete()

        except Exception as e:
            return task.failure(
                error_message="Error in TutorialProcessItemTaskHandler",
                error_details=str(e),
                max_retries=0,
                retry_timeout=0,
            )
