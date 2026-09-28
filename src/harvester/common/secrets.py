import os


class WorkerSecrets:
    def __init__(self):
        # get secrets from enviroment
        self.secrets = {}
        self.secrets["operaton_rest_user"] = (
            os.environ["OPERATON_REST_USER"] if "OPERATON_REST_USER" in os.environ else ""
        )
        self.secrets["operaton_rest_password"] = (
            os.environ["OPERATON_REST_PASSWORD"] if "OPERATON_REST_PASSWORD" in os.environ else ""
        )
        self.secrets["iam_client_id"] = os.environ["IAM_CLIENT_ID"] if "IAM_CLIENT_ID" in os.environ else None
        self.secrets["iam_client_secret"] = (
            os.environ["IAM_CLIENT_SECRET"] if "IAM_CLIENT_SECRET" in os.environ else None
        )

    def get_secret(self, key: str, default: str = ""):
        if key is not None and len(key) > 0:
            return self.secrets[key]
        else:
            return default


# Expose Config object for app to import
worker_secrets = WorkerSecrets()
