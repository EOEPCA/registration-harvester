from pathlib import Path
from typing import Any

import yaml


class WorkerConfig:
    """
    Load a YAML config file into a dictionary.
    """

    def __init__(self, config_path: Path):
        self.data = None

        if not config_path.is_file():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f)

        if self.data is None:
            raise ValueError(f"Expected top-level YAML mapping in {config_path}, got None")

        if not isinstance(self.data, dict):
            raise ValueError(f"Expected top-level YAML mapping in {config_path}, got {type(self.data).__name__}")

    def get_all(self) -> dict:
        return self.data

    def get(self, key: str, default: Any = None) -> dict:
        if key is not None and len(key) > 0:
            return self.data.get(key, default)
        else:
            return {}
