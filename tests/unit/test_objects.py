from typing import Self, AsyncGenerator

from adcm_aio_client.core.objects import Cluster
from adcm_aio_client.core.requesters import Requester, RequesterResponse


class DummyRequester(Requester):

    def __init__(self) -> None:
        pass

    def get(self: Self, path: str, query_params: dict) :
        ...

    def post(self: Self, path: str, data: dict) :
        ...

    def delete(self: Self, path: str) :
        ...

    def patch(self: Self, path: str, data: dict) :
        ...



def test_access_to_fields():
    cluster_data = {"id": 4, "name": "abadaba", "description": "Verybig\nand multiline \n\t Description yesss",
                    "bundle_id": 6}

    cluster = Cluster(requester=DummyRequester(), data=cluster_data)

    assert cluster.id == cluster_data["id"]
    assert cluster.name == cluster_data["name"]
    assert cluster.description == cluster_data["description"]
