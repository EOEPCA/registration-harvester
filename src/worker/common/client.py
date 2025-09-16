from flowable.external_worker_client import ExternalWorkerClient
from requests.auth import HTTPBasicAuth

from worker.common.config import worker_config
from worker.common.secrets import worker_secrets

import certifi


def customize_session(session):
    flowable_config = worker_config.get("flowable")
    if flowable_config.get("tls", False) and session is not None:
        session.verify = flowable_config.get("cacert", certifi.where())
        return session
    else:
        return None


flowable_config = worker_config.get("flowable")
flowable_client = ExternalWorkerClient(
    flowable_host=flowable_config.get("host"),
    auth=HTTPBasicAuth(
        worker_secrets.get_secret("flowable_user", ""),
        worker_secrets.get_secret("flowable_password", ""),
    ),
    customize_session=customize_session,
)
