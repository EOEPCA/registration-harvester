from operaton.external_task.external_task import ExternalTask, TaskResult

from worker.common.config import worker_config
from worker.common.iam import IAMClient
from worker.common.secrets import worker_secrets


class TaskHandler:
    TIMEOUT_1_MINUTE = 60000
    TIMEOUT_5_MINUTES = 3000000

    def __init__(self, handlers_config: dict = None):
        self.log_context = {}
        handler_name = self.__class__.__name__
        self.config_all = handlers_config.get(handler_name, {})

        # IAM client
        self.iam_client = None
        iam_config = worker_config.get_all().get("iam")
        if iam_config is not None and iam_config.get("enabled", False):
            iam_client_id = worker_secrets.get_secret("iam_client_id", None)
            iam_client_secret = worker_secrets.get_secret("iam_client_secret", None)
            token_url = iam_config.get("oidc_token_endpoint_url", None)
            if token_url is not None and iam_client_id is not None and iam_client_secret is not None:
                self.iam_client = IAMClient(
                    token_endpoint_url=token_url, client_id=iam_client_id, client_secret=iam_client_secret
                )

    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        raise NotImplementedError

    def get_config(self, key, default):
        return self.config_all.get(key, default)
