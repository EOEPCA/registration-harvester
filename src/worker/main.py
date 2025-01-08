from contextlib import asynccontextmanager

from fastapi import FastAPI

from worker.common.config import worker_config
from worker.common.log_utils import configure_logging
from worker.common.manager import SubscriptionManager

manager = SubscriptionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # logger = logging.getLogger("uvicorn.access")
    # handler = logging.StreamHandler()
    # handler.setFormatter(logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s"))
    # logger.addHandler(handler)
    yield
    # end all subs before fastapi server shutdown
    manager.unsubscribe_all()


app = FastAPI(lifespan=lifespan)


@app.get("/subscriptions")
def get_subscriptions():
    return {"subscriptions": manager.subscriptions_info()}


@app.get("/config")
def config():
    # show the configuration
    return {"config": worker_config.get_all()}


@app.get("/health")
def health():
    # health check
    return {"status": "Worker running"}
