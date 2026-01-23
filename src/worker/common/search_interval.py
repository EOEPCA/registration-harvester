import datetime

from dateutil.parser import parse

from worker.common.client import flowable_client
from worker.common.types import ExternalJob


def determine_search_interal(job: ExternalJob, timedelta_hours: float) -> tuple[str, str]:
    history = flowable_client.get_process_instance_history(job.process_instance_id)
    if "startTime" in history:
        current_time = parse(history["startTime"])
    else:
        current_time = datetime.datetime.now()
    end_time = datetime.datetime(current_time.year, current_time.month, current_time.day, current_time.hour)
    start_time = end_time - datetime.timedelta(hours=timedelta_hours)
    start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return start_time, end_time
