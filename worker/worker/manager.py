import logging
from datetime import datetime
from flowable.external_worker_client import ExternalWorkerClient
from requests.auth import HTTPBasicAuth
from worker.config import Config
from worker.log_utils import configure_logging

logger = logging.getLogger()
configure_logging()

def customize_session(session):
    if Config.FLOWABLE_USE_TLS and session is not None:
        session.verify = Config.FLOWABLE_HOST_CACERT
        return session
    else:
        return None
        
class SubscriptionManager:
    """
    """    

    def __init__(self):
        self.client = ExternalWorkerClient(
            flowable_host=Config.FLOWABLE_HOST, 
            auth=HTTPBasicAuth(Config.FLOWABLE_REST_USER, Config.FLOWABLE_REST_PASSWORD,),
            customize_session=customize_session)
        self.subscriptions = {}

    def subscriptions_info(self):
        subscriptions = {}
        for topic, workers in self.subscriptions.items():
            worker_details = []
            for worker_id, worker_data in workers.items():
                w = {
                    "worker_id": worker_id,
                    "thread": worker_data["thread"],
                    "jobs_completed": worker_data["jobs_completed"],
                    "start_time": worker_data["start_time"],
                    "settings": worker_data["settings"]
                }
                worker_details.append(w)
            subscriptions[topic] = worker_details
        return subscriptions

    def subscribe(self, topic: str, settings: dict):
        if topic not in self.subscriptions:
            self.subscriptions[topic] = {}

        now = datetime.now()
        worker_id = f"worker_{topic}_{int(now.timestamp())}"
        subscription = self.client.subscribe(topic, **settings)
        subscription.thread.getName
        self.subscriptions[topic][worker_id] = {
            "subscription": subscription,
            "thread": subscription.thread.ident,
            "jobs_completed": 0,
            "start_time": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "settings": settings
        }
        logger.info(f"Successfully subscribed worker {worker_id} to topic {topic} in thread {subscription.thread.ident}")

    def unsubscribe(self, topic: str, worker_id: str):
        if self.worker_exists(topic, worker_id):
            subscription = self.subscriptions[topic][worker_id]["subscription"]
            if subscription is not None:
                subscription.unsubscribe()
                logger.info(f"Successfully unsubscribed worker {worker_id} from topic {topic}")
            else:
                logger.error(f"Unable to unsubscribe worker {worker_id} from topic {topic}. Invalid subscription {str(subscription)}")
        else:
            logger.error(f"Worker {worker_id} not subscribed to topic {topic}")

    def unsubscribe_all(self):
        for topic in self.subscriptions:
            for worker_id in self.subscriptions[topic]:
                self.unsubscribe(topic=topic, worker_id=worker_id)

    def worker_exists(self, topic: str, worker_id: str):
        return topic in self.subscriptions and worker_id in self.subscriptions[topic]            

