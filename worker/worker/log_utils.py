import logging

def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] [%(thread)d] %(message)s",
        handlers=[logging.StreamHandler()],
        datefmt="%Y-%m-%dT%H:%M:%S"
    )    

def log_with_job(message, job=None, log_level='info', **kwargs):
    log_function = __get_log_function(log_level)

    if job is not None:
        log_function(f"[BPMN_TASK: {job.element_name}] {message}", **kwargs)
    else:
        log_function(message, **kwargs)

def log_with_context(message, context=None, log_level='info', **kwargs):
    context = context if context is not None else {}
    log_function = __get_log_function(log_level)

    log_context_prefix = __get_log_context_prefix(context)
    if log_context_prefix:
        log_function(f"{log_context_prefix} {message}", **kwargs)
    else:
        log_function(message, **kwargs)


def __get_log_context_prefix(context):
    log_context_prefix = ""
    if context:
        for k, v in context.items():
            if v is not None:
                log_context_prefix += f"[{k}:{v}]"
    return log_context_prefix


def __get_log_function(log_level):
    switcher = {
        'info': logging.info,
        'warning': logging.warning,
        'error': logging.error
    }
    return switcher.get(log_level, logging.info)