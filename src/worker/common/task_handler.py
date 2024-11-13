from worker.common.types import ExternalJob, JobResultBuilder, JobResult

class TaskHandler:
    def __init__(self, handlers_config: dict):
        self.log_context = {}
        handler_name = self.__class__.__name__
        self.config_all = handlers_config.get(handler_name, {})

        # Merge with base config
        self.subscription_config = {
            "lock_duration": "PT1M",
            "number_of_retries": 5,
            "scope_type": None, 
            "wait_period_seconds": 1,
            "number_of_tasks": 1,
            **self.config_all.get("subscription_config", {}),
        }
        self.handler_config = self.config_all.get("handler_config", {})
    
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        raise NotImplementedError