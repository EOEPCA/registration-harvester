from pathlib import Path

import yaml


class WorkerConfig:
    def __init__(self):
        self.config_worker = {}
        config_path = Path(__file__).parent.parent.parent.parent / "config.yaml"
        with open(config_path) as f:
            config_all = yaml.safe_load(f)
            self.config_worker = config_all["worker"]

    def get_all(self) -> dict:
        return self.config_worker

    def get(self, key: str) -> dict:
        if key is not None and len(key) > 0:
            return self.config_worker[key]
        else:
            return {}


# Expose Config object for app to import
worker_config = WorkerConfig()
