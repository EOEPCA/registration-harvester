import datetime
import logging
import time

import pytest
import requests
from pystac import Collection, Extent, SpatialExtent, TemporalExtent

from worker.common.iam import IAMClient

logger = logging.getLogger()

collection_id = "landsat-8-l1"
data_catalog_api_url = "https://eoapi.apx.develop.eoepca.org/stac"
iam_oidc_token_endpoint_url = "https://iam-auth.apx.develop.eoepca.org/realms/eoepca/protocol/openid-connect/token"
iam_client_id = "registration-harvester"
iam_client_secret = "Uj1nOvyZ8iFdRN8Iqaik0OkXDS66INU3"


@pytest.fixture
def collection():
    start_date = datetime.datetime(2018, 5, 21, 15, 44, 59)
    end_date = datetime.datetime(2018, 7, 8, 15, 45, 34)
    BBOX: list[float] = [-180, -90, 180, 90]
    collection = Collection(
        id=collection_id,
        description="Landsat 8 imagery",
        extent=Extent(
            spatial=SpatialExtent(BBOX),
            temporal=TemporalExtent([start_date, end_date]),
        ),
    )
    yield collection


@pytest.fixture
def oidc_client():
    client = IAMClient(
        token_endpoint_url=iam_oidc_token_endpoint_url, client_id=iam_client_id, client_secret=iam_client_secret
    )
    return client


def test_create_collection(collection, oidc_client):
    logger.info("Authenticate and request access token")
    token = oidc_client.get_access_token()

    # delete collection in case its already there
    response = requests.delete(
        url=f"{data_catalog_api_url}/collections/{collection_id}", headers={"Authorization": f"Bearer {token}"}
    )

    logger.info("Creating collection")
    token = oidc_client.get_access_token()
    response = requests.post(
        f"{data_catalog_api_url}/collections",
        json=collection.to_dict(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    time.sleep(2)

    logger.info("Checking if collection was created")
    response = requests.get(f"{data_catalog_api_url}/collections/{collection_id}")
    assert response.status_code == 200

    logger.info("Deleting previously created collection")
    token = oidc_client.get_access_token()
    response = requests.delete(
        url=f"{data_catalog_api_url}/collections/{collection_id}", headers={"Authorization": f"Bearer {token}"}
    )
    response.raise_for_status()

    # Ensure collection not found
    response = requests.get(f"{data_catalog_api_url}/collections/{collection_id}")
    assert response.status_code == 404

    # Wait until token expires
    # time.sleep(301)
    # token = oidc_client.get_access_token()
