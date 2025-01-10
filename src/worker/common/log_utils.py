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


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable string with minutes and seconds.

    Args:
        seconds (float): The duration in seconds

    Returns:
        str: Formatted string like "X Minutes Y Seconds" or "Y Seconds"
    """
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    return f"{minutes} Minutes {remaining_seconds} Seconds" if minutes > 0 else f"{remaining_seconds} Seconds"


def format_file_metrics(file_size_bytes: int, elapsed_time: float) -> str:
    """
    Calculate and format file metrics including file size (MB), speed (MB/s), and duration.

    Args:
        file_size_bytes (int): Size of the file in bytes
        elapsed_time (float): Time taken in seconds

    Returns:
        str: Formatted string with size, speed and duration metrics
    """
    file_size_mb = round(file_size_bytes / (1024 * 1024), 2)
    speed_mbs = round(file_size_mb / elapsed_time, 2)
    duration_str = format_duration(elapsed_time)
    return f"Size: {file_size_mb} MB, Speed: {speed_mbs} MB/s, Time: {duration_str}"
