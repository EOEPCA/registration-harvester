import argparse
import logging
import logging.config
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import APIRouter, FastAPI

from worker.common.config import WorkerConfig
from worker.common.log_utils import build_logging_config
from worker.common.manager import WorkerManager

# Default join timeout (seconds) when waiting for the worker threads to stop.
WORKER_JOIN_TIMEOUT = 60.0


class WorkerApp:
    """
    A self-contained worker service exposing endpoints over FastAPI
    while running its actual work on a background thread.

    Each instance owns its own shutdown event, logger and worker manager,
    so multiple instances can coexist safely in the same process.
    """

    def __init__(self, cli_args: list[str] | None = None):
        # Each instance gets its own stop signal
        self.stop_event = threading.Event()
        self.worker_manager: WorkerManager | None = None

        try:
            args = self._parse_args(cli_args)
            path = self._resolve_config_path(args)
            self.config = WorkerConfig(path)
        except (FileNotFoundError, ValueError, yaml.YAMLError) as e:
            raise ValueError(f"Error loading config: {e}") from e

        self.title = self.config.get("name", "Operaton Worker")
        self.version = self._get_version()
        self.host = self.config.get("host", "0.0.0.0")
        self.port = self.config.get("port", 8080)

        log_level = str(self.config.get("log_level", "INFO"))
        self.logging_config = build_logging_config(level=log_level, json_format=False)

        # Apply logging config so __init__/lifespan messages are formatted
        # consistently too, not just messages emitted after uvicorn starts.
        logging.config.dictConfig(self.logging_config)
        self.logger = logging.getLogger("worker.app")

        self.debug = log_level.lower() == "debug"

        # lifespan needs access to `self`, so define it here as a closure
        self.app = FastAPI(
            title=self.title,
            version=self.version,
            debug=self.debug,
            lifespan=self._lifespan,
        )

        self._register_routes()

    def _parse_args(self, cli_args: list[str] | None = None) -> argparse.Namespace:
        description = """\
Run the worker app

A YAML configuration file is needed. The file path is determined in following order (first match wins):
    1. --config command line argument
    2. CONFIG_FILE_PATH environment variable
    3. default: "config.yaml"
"""

        epilog = """\
Examples:
    python main.py                            # uses config.yaml
    python main.py --config other.yaml        # uses other.yaml
    CONFIG_FILE_PATH=prod.yaml python main.py # uses prod.yaml
"""
        parser = argparse.ArgumentParser(
            add_help=True,
            description=description,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "--config",
            type=str,
            default=None,
            help="Path to YAML config file",
        )
        args, _ = parser.parse_known_args(cli_args)
        return args

    def _resolve_config_path(self, args: argparse.Namespace) -> Path:
        """Determine the config file path using the priority order above.

        Logging isn't configured yet at this point (we need the config file
        to know the desired log level), so these use print() deliberately.
        """
        if args.config:
            print(f"Reading worker config from {args.config} as provided by --config argument")
            return Path(args.config)

        env_path = os.environ.get("CONFIG_FILE_PATH")
        if env_path:
            print(f"Reading worker config from {env_path} as provided by CONFIG_FILE_PATH env variable")
            return Path(env_path)

        print("Reading worker config from config.yaml as default")
        return Path("config.yaml")

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        self.logger.info(
            f"Starting {self.title} version {self.version} with debug={self.debug} on {self.host}:{self.port}"
        )
        t = threading.Thread(target=self.start_worker_threads, name="worker-thread")
        t.start()

        yield

        # End all worker threads before fastapi server shutdown.
        self.logger.info("Shutdown requested, signalling worker threads to stop...")
        self.stop_event.set()
        # t.join(timeout=WORKER_JOIN_TIMEOUT)
        t.join()
        if t.is_alive():
            self.logger.warning(f"Worker thread did not stop within {WORKER_JOIN_TIMEOUT}s; continuing shutdown anyway")
        else:
            self.logger.info("Worker thread stopped cleanly")

    def _get_version(self) -> str:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("worker")
        except PackageNotFoundError:
            return "unknown"

    def _register_routes(self):
        router = APIRouter()

        @router.get("/config")
        async def config():
            return {"config": self.config.get_all()}

        @router.get("/health")
        async def health():
            return {"status": f"{self.title} version {self.version} is running"}

        @router.get("/version")
        async def version():
            return {"version": self.version}

        self.app.include_router(router)

    def start_worker_threads(self):
        """Entry point for the background worker thread."""
        self.worker_manager = WorkerManager(config=self.config, shutdown_event=self.stop_event)

    def run(self):
        """Run app from command line using uvicorn if available."""
        try:
            import uvicorn
        except ImportError as e:
            raise RuntimeError("Uvicorn must be installed in order to use command") from e

        uvicorn.run(self.app, host=self.host, port=self.port, log_config=self.logging_config)
