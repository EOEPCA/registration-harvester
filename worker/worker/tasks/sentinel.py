from worker.log_utils import configure_logging, log_with_context

configure_logging()

def sentinel_check_data(job, worker_result_builder):
    log_context = {
        "JOB": job.id,
        "PROCESS_INSTANCE": job.process_instance_id,
        "TASK": job.element_name,
    }
    log_with_context("sentinel_check_data", log_context)    

    # job variables
    # for v in job.variables:
    #    log_variable(v)

    # execute task and build result
    result =  worker_result_builder.success()
    
    # result variables
    # result.variable_string("zip_file_path", "/path/to/zip")
    #for v in result._variables:
    #    log_variable(v)
    
    return result

def sentinel_log_data(job, worker_result_builder):
    log_context = {
        "JOB": job.id,
        "PROCESS_INSTANCE": job.process_instance_id,
        "TASK": job.element_name,
    }
    log_with_context("sentinel_log_data", log_context) 
    
    result =  worker_result_builder.success()
    return result
