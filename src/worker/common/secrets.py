import os


class WorkerSecrets:
    def __init__(self):
        # get secrets from enviroment
        self.secrets = {}
        self.secrets["cdse_user"] = os.environ["CDSE_USER"] if "CDSE_USER" in os.environ else ""
        self.secrets["cdse_password"] = os.environ["CDSE_PASSWORD"] if "CDSE_PASSWORD" in os.environ else ""
        self.secrets["m2m_user"] = os.environ["M2M_USER"] if "M2M_USER" in os.environ else ""
        self.secrets["m2m_password"] = os.environ["M2M_PASSWORD"] if "M2M_PASSWORD" in os.environ else ""
        self.secrets["flowable_user"] = os.environ["FLOWABLE_USER"] if "FLOWABLE_USER" in os.environ else ""
        self.secrets["flowable_password"] = os.environ["FLOWABLE_PASSWORD"] if "FLOWABLE_PASSWORD" in os.environ else ""

    def get_secret(self, key: str, default: str) -> dict:
        if key is not None and len(key) > 0:
            return self.secrets[key]
        else:
            return default


# Expose Config object for app to import
worker_secrets = WorkerSecrets()
