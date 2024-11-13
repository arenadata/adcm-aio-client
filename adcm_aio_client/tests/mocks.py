# Define a mock response object to simulate API/database responses
import json
from typing import Self

from httpx import Response

from adcm_aio_client.core.requesters import HTTPXRequesterResponse, DefaultRequester

page_content = [
    {
        "id": 1,
        "name": "cluster_1",
        "description": "cluster_1",
        "state": "created",
        "multiState": [],
        "status": "down",
        "prototype": {
            "id": 2,
            "name": "cluster_one",
            "displayName": "cluster_one",
            "version": "1.0",
        },
        "concerns": [],
        "isUpgradable": False,
        "mainInfo": None,
    },
    {
        "id": 2,
        "name": "cluster_2",
        "description": "cluster_2",
        "state": "created",
        "multiState": [],
        "status": "down",
        "prototype": {
            "id": 2,
            "name": "cluster_2",
            "displayName": "cluster_2",
            "version": "1.0",
        },
        "concerns": [],
        "isUpgradable": False,
        "mainInfo": None,
    },
    {
        "id": 3,
        "name": "cluster_3",
        "description": "cluster_3",
        "state": "created",
        "multiState": [],
        "status": "down",
        "prototype": {
            "id": 3,
            "name": "cluster_3",
            "displayName": "cluster_3",
            "version": "1.0",
        },
        "concerns": [],
        "isUpgradable": False,
        "mainInfo": None,
    },
]


class MockRequester(DefaultRequester):
    response_retrieve = Response(
        status_code=200,  # Assuming a successful response
        headers={"Content-Type": "application/json"},
        content=json.dumps([page_content[0]]),
    )

    response_list = Response(
        status_code=200,  # Assuming a successful response
        headers={"Content-Type": "application/json"},
        content=json.dumps(page_content),
    )

    async def get(self: Self, *path: str | int, query_params: dict | None = None) -> HTTPXRequesterResponse:
        # This function simulates retrieval of data
        if not isinstance(path, int) and not query_params or "id" not in query_params:
            if query_params and not "limit" in query_params and not "offset" in query_params:
                return HTTPXRequesterResponse(response=MockRequester.response_list)
            return HTTPXRequesterResponse(response=MockRequester.response_list)
        if query_params and "id" in query_params and query_params["id"] > 3:
            return HTTPXRequesterResponse(response=Response(status_code=404, content=json.dumps([])))
        return HTTPXRequesterResponse(response=MockRequester.response_retrieve)
