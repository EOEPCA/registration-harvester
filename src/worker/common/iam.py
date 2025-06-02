import datetime
import logging

import requests

logger = logging.getLogger()


class IAMClient:
    def __init__(self, token_endpoint_url, client_id, client_secret):
        self._oidc_token_endpoint_url = token_endpoint_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = requests.Session()
        self._access_token_expiration_date = None
        self._access_token = None

    def get_access_token(self):
        now = datetime.datetime.now()
        if self._access_token is not None and self._access_token_expiration_date is not None:
            if self._access_token_expiration_date < now:
                logger.info("Current token expired. Updating...")
                self.update_token()
            else:
                logger.info(f"Current token still valid. Expires at {self._access_token_expiration_date}")
        else:
            # no token has been acquired before
            self.update_token()

        return self._access_token

    def update_token(self):
        if self._client_id is None or self._client_secret is None:
            raise ValueError("IAM credentials missing")

        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }
        headers = {"cache-control": "no-cache"}
        response = self._session.post(url=self._oidc_token_endpoint_url, headers=headers, data=body).json()
        token_type = response.get("token_type")
        if token_type is None or token_type != "Bearer":
            raise ValueError(f"Invalid token type {token_type}")

        now = datetime.datetime.now()
        self._access_token_expiration_date = now + datetime.timedelta(seconds=response.get("expires_in"))
        self._access_token = response.get("access_token")
        logger.info(f"Successfully acquired token which expires at {self._access_token_expiration_date}")
