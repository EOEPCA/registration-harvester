from worker.common.log_utils import configure_logging, log_with_job

configure_logging()


def sentinel_discover_data(job, worker_result_builder):
    log_with_job(message="Discovering new sentinel data ...", job=job)
    # job variables
    # for v in job.variables:
    #    log_variable(v)

    # execute task and build result
    result = worker_result_builder.success()

    # result variables
    # result.variable_string("zip_file_path", "/path/to/zip")
    # for v in result._variables:
    #    log_variable(v)

    return result


def sentinel_download_data(job, worker_result_builder):
    log_with_job(message="Downloading data ...", job=job)
    result = worker_result_builder.success()
    return result


def sentinel_unzip(job, worker_result_builder):
    log_with_job(message="Unzipping ...", job=job)
    result = worker_result_builder.success()
    return result


def sentinel_check_integrity(job, worker_result_builder):
    log_with_job(message="Checking integrity ...", job=job)
    result = worker_result_builder.success()
    return result


def sentinel_extract_metadata(job, worker_result_builder):
    log_with_job(message="Extracting metadata and creating STAC item ...", job=job)
    result = worker_result_builder.success()
    return result


def sentinel_register_metadata(job, worker_result_builder):
    log_with_job(message="Registering STAC item ...", job=job)
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
}
