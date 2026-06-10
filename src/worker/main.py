import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from worker.common.config import worker_config
from worker.common.log_utils import configure_logging
from worker.common.manager import WorkerManager

stop_event = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Configure logging")
    configure_logging()

    logging.info("Start worker threads and subscribe to topics")
    t = threading.Thread(target=start_worker_threads)
    t.start()

    yield
    # end all worker threads before fastapi server shutdown
    stop_event.set()
    t.join()


app = FastAPI(lifespan=lifespan)


@app.get("/config")
def config():
    # show the configuration
    return {"config": worker_config.get_all()}


@app.get("/health")
def health():
    # health check
    return {"status": "Worker running"}


def start_worker_threads():
    WorkerManager(shutdown_event=stop_event)
