import datetime

from dateutil.parser import parse
from operaton.client.engine_client import EngineClient
from operaton.external_task.external_task import ExternalTask

from worker.common.config import worker_config


def determine_search_interal(task: ExternalTask, timedelta_hours: float) -> tuple[str, str]:
    engine_config = worker_config.get("bpm_engine")
    client = EngineClient(engine_base_url=engine_config.get("url"), config=engine_config)
    # TODO Add get_process_instance_history to operaton external task client
    history = client.get_process_instance_history(task.get_process_instance_id())
    if "startTime" in history:
        current_time = parse(history["startTime"])
    else:
        current_time = datetime.datetime.now()
    end_time = datetime.datetime(current_time.year, current_time.month, current_time.day, current_time.hour)
    start_time = end_time - datetime.timedelta(hours=timedelta_hours)
    start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return start_time, end_time
