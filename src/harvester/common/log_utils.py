import logging
import logging.config
import sys


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


def build_logging_config(level: str = "INFO", json_format: bool = False) -> dict:
    """Build a dictConfig that covers root, uvicorn, and app loggers uniformly."""

    # text_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    text_format = "%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s | %(thread)d | %(message)s"
    json_fields = '{"time": "%(asctime)s.%(msecs)03d", "level": "%(levelname)s", "thread": "%(thread)d", "message": "%(message)s"}'

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": json_fields if json_format else text_format,
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
            "access": {
                "format": text_format,
                # "format": '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(client_addr)s - "%(request_line)s" %(status_code)s',
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
            },
        },
        "loggers": {
            "app.worker": {"handlers": ["default"], "level": level, "propagate": False},
            # Ensure libs use same handler/format and reduce log noise when in DEBUG mode
            "urllib3.connectionpool": {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "fsspec.local": {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "eodag.core": {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "eodag.provider": {"handlers": ["default"], "level": "WARNING", "propagate": False},
            "eodag.download.base": {"handlers": ["default"], "level": "WARNING", "propagate": False},
            # uvicorn's own loggers — reuse the same handler/format
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": level, "propagate": False},
            "uvicorn.asgi": {"handlers": ["access"], "level": level, "propagate": False},
        },
        "root": {
            "handlers": ["default"],
            "level": level,
        },
    }


def setup_logging(level: str = "INFO", json_format: bool = False):
    logging.config.dictConfig(build_logging_config(level=level, json_format=json_format))
