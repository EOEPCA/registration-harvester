from worker.common.config import worker_config
from worker.common.iam import IAMClient
from worker.common.secrets import worker_secrets
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

        # IAM client
        iam_client_id = worker_secrets.get_secret("iam_client_id", None)
        iam_client_secret = worker_secrets.get_secret("iam_client_secret", None)
        iam_oidc_token_endpoint_url = "https://iam-auth.develop.eoepca.org/realms/eoepca/protocol/openid-connect/token"
        iam_config = worker_config.get_all().get("iam")
        if iam_config is not None:
            token_url = iam_config.get("oidc_token_endpoint_url")
            if token_url is not None:
                iam_oidc_token_endpoint_url = token_url

        self.iam_client = IAMClient(
            token_endpoint_url=iam_oidc_token_endpoint_url, client_id=iam_client_id, client_secret=iam_client_secret
        )

    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        raise NotImplementedError

    def task_failure(self, error, error_msg, result, retries=3, timeout="PT10M") -> JobResult:
        return result.failure().error_message(error).error_details(error_msg).retries(retries).retry_timeout(timeout)

    def get_config(self, key, default):
        return self.config_all.get(key, default)
