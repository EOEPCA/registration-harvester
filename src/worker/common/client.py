from flowable.external_worker_client import ExternalWorkerClient
from worker.common.config import Config
from requests.auth import HTTPBasicAuth


def customize_session(session):
    if Config.FLOWABLE_USE_TLS and session is not None:
        session.verify = Config.FLOWABLE_HOST_CACERT
        return session
    else:
        return None


flowableClient = ExternalWorkerClient(
    flowable_host=Config.FLOWABLE_HOST,
    auth=HTTPBasicAuth(
        Config.FLOWABLE_REST_USER,
        Config.FLOWABLE_REST_PASSWORD,
    ),
    customize_session=customize_session,
)
