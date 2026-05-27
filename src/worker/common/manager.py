import importlib
import logging
import socket
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime

from operaton.external_task.external_task_worker import ExternalTaskWorker

from worker.common.config import worker_config
from worker.common.log_utils import configure_logging
from worker.common.secrets import worker_secrets

logger = logging.getLogger()
configure_logging()


class SubscriptionManager:
    """ """

    def __init__(self):
        self.exernal_task_worker = {}
        self._create_workers_from_config()

    def _create_workers_from_config(self):
        # Global task settings
        engine_config = worker_config.get("bpm_engine")
        task_config = {
            "base_url": engine_config.get("url"),
            "lockDuration": engine_config.get("lock_duration", 300000),
            "retries": engine_config.get("retries", 3),
            "retryTimeout": engine_config.get("retry_timeout", 30000),
            "isDebug": worker_config.get_all().get("is_debug", False),
            "asyncResponseTimeout": engine_config.get("async_response_timeout", 120000),
            "sleepSeconds": engine_config.get("sleep_seconds", 15),
            "httpTimeoutMillis": engine_config.get("http_timeout_millis", 420000),
            "timeoutDeltaMillis": engine_config.get("timeout_delta_millis", 300000),
            "auth_basic": {
                "username": worker_secrets.get_secret("operaton_rest_user", ""),
                "password": worker_secrets.get_secret("operaton_rest_password", ""),
            },
        }

        # Overall number of needed worker threads
        num_workers_total = sum(topic.get("workers", 1) for _, topic in worker_config.get("topics").items())

        # Subscribe
        with ThreadPoolExecutor(max_workers=num_workers_total) as executor:
            for topic, topic_config in worker_config.get("topics").items():
                # Create TaskHandler instance for each topic and save it to map
                module = importlib.import_module(topic_config.get("module"))
                handler_class = getattr(module, topic_config.get("handler"))
                handler = handler_class(worker_config.get("handlers"))

                # Update task_config with topic specific configuration
                if "sleep_seconds" in topic_config:
                    task_config["sleepSeconds"] = topic_config.get("sleep_seconds")
                if "lock_duration" in topic_config:
                    task_config["lockDuration"] = topic_config.get("lock_duration")
                if "retries" in topic_config:
                    task_config["retries"] = topic_config.get("retries")
                task_config["parallel_tasks"] = topic_config.get("parallel_tasks", 1)

                process_variables = topic_config.get("process_variables")
                num_workers = topic_config.get("workers", 1)

                # Create worker for topic
                now = datetime.now()
                for index in range(0, num_workers):
                    worker_id = f"worker_{socket.gethostname()}_{topic}_{index}"
                    external_task_worker = ExternalTaskWorker(
                        base_url=task_config["base_url"],
                        worker_id=worker_id,
                        config=task_config,
                    )
                    executor.submit(
                        external_task_worker.subscribe,
                        topic,
                        handler.execute,
                        process_variables=process_variables,
                    )
                    # Save worker and its config
                    self.exernal_task_worker[topic][worker_id] = {
                        "worker": external_task_worker,
                        "jobs_completed": 0,
                        "start_time": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                        "settings": task_config,
                    }
                    logger.info(f"Successfully subscribed worker {worker_id} to topic {topic}")

    def subscriptions_info(self):
        workers = {}
        for topic, workers in self.exernal_task_worker.items():
            worker_details = []
            for worker_id, worker_data in workers.items():
                w = {
                    "worker_id": worker_id,
                    "jobs_completed": worker_data["jobs_completed"],
                    "start_time": worker_data["start_time"],
                    "settings": worker_data["settings"],
                }
                worker_details.append(w)
            workers[topic] = worker_details
        return workers

    def unsubscribe(self, topic: str, worker_id: str):
        pass
        # TODO Implement unsubscribe
        # if self.worker_exists(topic, worker_id):
        #     subscription = self.subscriptions[topic][worker_id]["subscription"]
        #     if subscription is not None:
        #         subscription.unsubscribe()
        #         logger.info(f"Successfully unsubscribed {worker_id} from {topic}")
        #     else:
        #         logger.error(
        #             f"Unable to unsubscribe {worker_id} from {topic}. Invalid subscription {str(subscription)}"
        #         )
        # else:
        #     logger.error(f"Worker {worker_id} not subscribed to topic {topic}")

    def unsubscribe_all(self):
        for topic in self.exernal_task_worker:
            for worker_id in self.exernal_task_worker[topic]:
                self.unsubscribe(topic=topic, worker_id=worker_id)

    def worker_exists(self, topic: str, worker_id: str):
        return topic in self.exernal_task_worker and worker_id in self.exernal_task_worker[topic]
