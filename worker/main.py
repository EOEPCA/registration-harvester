from fastapi import FastAPI
from contextlib import asynccontextmanager
from worker.config import Config
from worker.manager import SubscriptionManager
from worker.log_utils import configure_logging

manager = SubscriptionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    #logger = logging.getLogger("uvicorn.access")
    #handler = logging.StreamHandler()
    #handler.setFormatter(logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s"))
    #logger.addHandler(handler)
    yield
    # end all subs before fastapi server shutdown
    manager.unsubscribe_all()

app = FastAPI(lifespan=lifespan)

subcriptions = Config.default_subscriptions
for topic in subcriptions:
    manager.subscribe(topic=topic, settings=subcriptions[topic])

@app.get("/subscriptions")
def get_subscriptions():
    return {"subscriptions": manager.subscriptions_info()}
    
@app.get("/config")
def config():
    # show the configuration
    config = {}
    for field in Config.__annotations__:
        value = getattr(Config, field, None)
        config[field]=value
    return {"config": config}

@app.get("/health")
def health():
    # health check
    return {"status": "Worker running"}
