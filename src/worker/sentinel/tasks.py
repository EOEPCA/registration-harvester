import json
from worker.common.log_utils import configure_logging, log_with_job, log_variable

configure_logging()


def sentinel_discover_data(job, worker_result_builder):
    log_with_job(message="Discovering new sentinel data ...", job=job)

    # discovering scenes
    scenes = []
    scene1 = {
        "scene": {
            "name": "scene1"
        }        
    }
    scene2 = {
        "scene": {
            "name": "scene2"
        }  
    }    
    scenes.append(scene1)
    #scenes.append(scene2)

    # build result
    result = worker_result_builder.success()
    result.variable_json(name="scenes", value=scenes)

    for v in result._variables:
        log_variable(variable=v, job=job, log_level="info")

    return result

def sentinel_order_data(job, worker_result_builder):
    log_with_job(message="Ordering data ...", job=job)
    result = worker_result_builder.success()
    return result

def sentinel_download_data(job, worker_result_builder):
    log_with_job(message="Downloading data ...", job=job)

    # get job variables
    for v in job.variables:
        log_variable(variable=v, job=job, log_level="info")
        
    result = worker_result_builder.success()
    return result

def sentinel_unzip(job, worker_result_builder):
    log_with_job(message="Unzipping ...", job=job)

    # get job variables
    for v in job.variables:
        log_variable(variable=v, job=job, log_level="info")
        
    result = worker_result_builder.success()
    return result


def sentinel_check_integrity(job, worker_result_builder):
    log_with_job(message="Checking integrity ...", job=job)

    # get job variables
    for v in job.variables:
        log_variable(variable=v, job=job, log_level="info")

    job_vars = {}
    for v in job.variables:
        job_vars[v.name] = v.value

    scene = job_vars["scene"]
    log_with_job(f"Input variable: scene={scene}")
    
    scene['collection'] = "sentinel-1"
    #scene['collection'] = ""
    log_with_job(f"Output variable: scene={scene}")
    result = worker_result_builder.success()
    result.variable_string(name="collection", value=scene['collection'])

    return result


def sentinel_extract_metadata(job, worker_result_builder):
    log_with_job(message="Extracting metadata and creating STAC item ...", job=job)

    # get job variables
    for v in job.variables:
        log_variable(variable=v, job=job, log_level="info")
        
    result = worker_result_builder.success()
    return result


def sentinel_register_metadata(job, worker_result_builder):
    log_with_job(message="Registering STAC item ...", job=job)

    # get job variables
    for v in job.variables:
        log_variable(variable=v, job=job, log_level="info")
        
    result = worker_result_builder.success()
    return result

def sentinel_inventory_update(job, worker_result_builder):
    log_with_job(message="Updating inventory ...", job=job)

    # get job variables
    for v in job.variables:
        log_variable(variable=v, job=job, log_level="info")
        
    result = worker_result_builder.success()
    return result


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
