import os
from pathlib import Path

import yaml


class WorkerConfig:
    def __init__(self):
        self.config_worker = {}
        config_path_default = Path(__file__).parent.parent.parent.parent / "config-sentinel.yaml"
        config_path = os.environ.get("CONFIG_FILE_PATH", config_path_default)
        with open(config_path) as f:
            self.config_worker = yaml.safe_load(f)

    def get_all(self) -> dict:
        return self.config_worker

    def get(self, key: str) -> dict:
        if key is not None and len(key) > 0:
            return self.config_worker[key]
        else:
            return {}


# Expose Config object for app to import
worker_config = WorkerConfig()
