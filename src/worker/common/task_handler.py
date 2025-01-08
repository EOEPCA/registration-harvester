from worker.common.types import ExternalJob, JobResult, JobResultBuilder


class TaskHandler:
    def __init__(self, handlers_config: dict):
        self.log_context = {}
        handler_name = self.__class__.__name__
        self.config_all = handlers_config.get(handler_name, {})

        # Merge with base config
        self.subscription_config = {
            "lock_duration": "PT10M",
            "number_of_retries": 5,
            "scope_type": None,
            "wait_period_seconds": 1,
            "number_of_tasks": 1,
            **self.config_all.get("subscription", {}),
        }

    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        raise NotImplementedError

    def task_failure(self, error, error_msg, result, retries=3, timeout="PT10M") -> JobResult:
        return result.failure().error_message(error).error_details(error_msg).retries(retries).retry_timeout(timeout)

    def get_config(self, key, default):
        return self.config_all.get(key, default)
