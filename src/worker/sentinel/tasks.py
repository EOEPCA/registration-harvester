from worker.common.log_utils import configure_logging, log_with_job
from worker.common.types import ExternalJob, JobResultBuilder, JobResult

configure_logging()


def sentinel_discover_data(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Discovering new sentinel data ...", job=job)

    log_with_job(f"Process Instance Id: {job.process_instance_id}", job=job)

    # get order id
    order_id = job.get_variable("order_id")
    if order_id is None:
        order_id = job.process_instance_id

    # discovering scenes
    scenes = []
    scene1 = {"scene": {"name": "scene1"}}
    # scene2 = {"scene": {"name": "scene2"}}
    scenes.append(scene1)
    # scenes.append(scene2)

    # build result
    return result.success().variable_json(name="scenes", value=scenes)


def sentinel_order_data(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Ordering data ...", job=job)
    return result.success()


def sentinel_download_data(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Downloading data ...", job=job)

    # get job variables
    log_with_job(job.get_variable("scene"), job)

    return result.success()


def sentinel_unzip(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Unzipping ...", job=job)

    return result.success()


def sentinel_check_integrity(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Checking integrity ...", job=job)

    # get job variables
    scene = job.get_variable("scene")
    log_with_job(f"Input variable: scene={scene}", job)

    # scene["collection"] = "sentinel-1"
    scene["collection"] = ""
    log_with_job(f"Output variable: scene={scene}", job)

    return (
        result.success()
        .variable_string(name="collection", value=scene["collection"])
        .variable_json(name="scene", value=scene)
    )


def sentinel_extract_metadata(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Extracting metadata and creating STAC item ...", job=job)

    # get job variables
    log_with_job(f"scene={job.get_variable("scene")}", job)
    log_with_job(f"collection={job.get_variable("collection")}", job)

    return result.success()


def sentinel_register_metadata(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Registering STAC item ...", job=job)

    return result.success()


def sentinel_inventory_update(job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
    log_with_job(message="Updating inventory ...", job=job)

    # get job variables
    log_with_job(f"scene={job.get_variable("scene")}", job)
    log_with_job(f"collection={job.get_variable("collection")}", job)

    return result.success()


tasks_config = {
    "sentinel_discover_data": {
        "callback_handler": sentinel_discover_data,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_order_data": {
        "callback_handler": sentinel_order_data,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_download_data": {
        "callback_handler": sentinel_download_data,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_unzip": {
        "callback_handler": sentinel_unzip,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_check_integrity": {
        "callback_handler": sentinel_check_integrity,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_extract_metadata": {
        "callback_handler": sentinel_extract_metadata,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_register_metadata": {
        "callback_handler": sentinel_register_metadata,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 1,
    },
    "sentinel_inventory_update": {
        "callback_handler": sentinel_inventory_update,
        "lock_duration": "PT1M",
        "number_of_retries": 5,
        "scope_type": None,
        "wait_period_seconds": 1,
        "number_of_tasks": 10,
    },
}
