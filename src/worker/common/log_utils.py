import logging

from worker.common.config import worker_config


def configure_logging():
    logging.basicConfig(
        level=__get_log_level(worker_config.get("log_level")),
        format="%(asctime)s.%(msecs)03d [%(levelname)s] [%(thread)d] %(message)s",
        handlers=[logging.StreamHandler()],
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def log_with_context(message, context=None, log_level="info", **kwargs):
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
        log_context_prefix = "["
        for k, v in context.items():
            if v is not None:
                log_context_prefix += f"{k}: {v} "
        log_context_prefix = log_context_prefix.strip() + "]"
    return log_context_prefix


def __get_log_level(log_level: str):
    switcher = {"info": logging.INFO, "debug": logging.DEBUG, "warning": logging.WARNING, "error": logging.ERROR}
    return switcher.get(log_level.lower(), logging.INFO)


def __get_log_function(log_level: str):
    switcher = {"info": logging.info, "debug": logging.debug, "warning": logging.warning, "error": logging.error}
    return switcher.get(log_level.lower(), logging.info)
