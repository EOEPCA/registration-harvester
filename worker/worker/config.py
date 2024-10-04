import os
from typing import get_type_hints, Union
from dotenv import load_dotenv
from worker.tasks.sentinel import sentinel_check_data, sentinel_log_data

# Load configuration
# The value of a variable is the first of the values found in:
# - the environment
# - the .env file
# - the default value, if provided
load_dotenv(".env")

class HarvesterConfigError(Exception):
    pass

def _parse_bool(val: Union[str, bool]) -> bool:  # pylint: disable=E1136
    return val if type(val) == bool else val.lower() in ['true', 'yes', '1']

class HarvesterConfig:
    # Fields and default values
    FLOWABLE_HOST          : str = "https://registration-harvester-api.develop.eoepca.org/flowable-rest"
    FLOWABLE_REST_USER     : str = "eoepca"
    FLOWABLE_REST_PASSWORD : str = "eoepca"
    FLOWABLE_HOST_CACERT   : str = "./etc/eoepca-ca-chain.pem"
    FLOWABLE_USE_TLS       : bool = True

    # Name in lower case to skip mapping of env variables
    default_subscriptions = {
        "sentinel_check_data": {
            "callback_handler": sentinel_check_data,
            "lock_duration": "PT1M",
            "number_of_retries": 5,
            "scope_type": None,
            "wait_period_seconds": 1,
            "number_of_tasks": 1
        },
        "sentinel_log_data": {
            "callback_handler": sentinel_log_data,
            "lock_duration": "PT1M",
            "number_of_retries": 5,
            "scope_type": None,
            "wait_period_seconds": 1,
            "number_of_tasks": 1
        },
    }    

    """
    Map environment variables to class fields according to these rules:
      - Field won't be parsed unless it has a type annotation
      - Field will be skipped if not in all caps
      - Class field and environment variable name are the same
    """
    def __init__(self, env):
        for field in self.__annotations__:
            if not field.isupper():
                continue

            # Raise AppConfigError if required field not supplied
            default_value = getattr(self, field, None)
            if default_value is None and env.get(field) is None:
                raise HarvesterConfigError('The {} field is required'.format(field))
            
            # Cast env var value to expected type and raise AppConfigError on failure
            try:
                var_type = get_type_hints(HarvesterConfig)[field]
                if var_type == bool:
                    value = _parse_bool(env.get(field, default_value))
                else:
                    value = var_type(env.get(field, default_value))            
                self.__setattr__(field, value)
            except ValueError:
                raise HarvesterConfigError('Unable to cast value of "{}" to type "{}" for "{}" field'.format(
                    env[field],
                    var_type,
                    field
                )
            )

    def __repr__(self):
        return str(self.__dict__)
    
    def get_default_subscriptions(self):
        subscriptions = {
            "sentinel_check_data": {
                "callback_handler": sentinel_check_data,
                "lock_duration": "PT1M",
                "number_of_retries": 5,
                "scope_type": None,
                "wait_period_seconds": 30,
                "number_of_tasks": 1
            },
            "sentinel_log_data": {
                "callback_handler": sentinel_log_data,
                "lock_duration": "PT1M",
                "number_of_retries": 5,
                "scope_type": None,
                "wait_period_seconds": 30,
                "number_of_tasks": 1
            },
}
        return {}
    
# Expose Config object for app to import
Config = HarvesterConfig(os.environ)