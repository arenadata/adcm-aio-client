from dataclasses import dataclass
from functools import partial
from typing import Any, Self
import json

import pytest

from adcm_aio_client.core.errors import ResponseDataConversionError, ResponseError
from adcm_aio_client.core.requesters import DefaultRequester, HTTPXRequesterResponse

pytestmark = [pytest.mark.asyncio]


@dataclass()
class HTTPXLikeResponse:
    status_code: int = 200
    data: str = "{}"
    content: bytes = b""

    def json(self: Self) -> Any:  # noqa: ANN401
        return json.loads(self.data)


def build_mock_response(response: HTTPXLikeResponse):  # noqa: ANN201
    async def return_response(*a, **kw) -> HTTPXLikeResponse:  # noqa: ANN002, ANN003
        _ = a, kw
        return response

    return return_response


@pytest.fixture()
def httpx_requester() -> DefaultRequester:
    return DefaultRequester(base_url="dummy", retries=1, retry_interval=0)


@pytest.mark.parametrize(
    ("method", "status_code", "call_kwargs"),
    [("get", 200, {}), ("post", 201, {"data": {}}), ("patch", 299, {"data": {}}), ("delete", 204, {})],
    ids=lambda value: value if not isinstance(value, dict) else "kw",
)
async def test_successful_request(
    method: str, status_code: int, call_kwargs: dict, httpx_requester: DefaultRequester, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = httpx_requester

    response = HTTPXLikeResponse(status_code=status_code, data="{}")
    return_response = build_mock_response(response)
    monkeypatch.setattr(requester.client, "request", return_response)

    result = await getattr(requester, method)(**call_kwargs)

    assert isinstance(result, HTTPXRequesterResponse)
    assert result.response is response
    assert result.as_dict() == {}


async def test_successful_response_data_conversion(
    httpx_requester: DefaultRequester, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = httpx_requester

    return_response = build_mock_response(HTTPXLikeResponse(data="{}"))
    monkeypatch.setattr(requester.client, "request", return_response)

    response = await requester.get()
    assert response.as_dict() == {}

    return_response = build_mock_response(HTTPXLikeResponse(data="[]"))
    monkeypatch.setattr(requester.client, "request", return_response)

    response = await requester.delete()
    assert response.as_list() == []


@pytest.mark.parametrize("status_code", [300, 301, 399, 400, 403, 499, 500, 501, 599])
async def test_raising_client_error_for_status(
    status_code: int, httpx_requester: DefaultRequester, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = httpx_requester

    return_response = build_mock_response(HTTPXLikeResponse(status_code=status_code, data=""))
    monkeypatch.setattr(requester.client, "request", return_response)

    for method in (
        partial(requester.get, query={}),
        partial(requester.post, data={}),
        partial(requester.patch, data={}),
        requester.delete,
    ):
        with pytest.raises(ResponseError):
            await method()


async def test_response_as_dict_error_on_wrong_type(
    httpx_requester: DefaultRequester, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = httpx_requester

    for incorrect_data in ("[]", "{,"):
        return_response = build_mock_response(HTTPXLikeResponse(data=incorrect_data))
        monkeypatch.setattr(requester.client, "request", return_response)

        response = await requester.get()

        with pytest.raises(ResponseDataConversionError):
            response.as_dict()


async def test_response_as_list_error_on_wrong_type(
    httpx_requester: DefaultRequester, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = httpx_requester

    for incorrect_data in ("{}", "[,"):
        return_response = build_mock_response(HTTPXLikeResponse(data=incorrect_data))
        monkeypatch.setattr(requester.client, "request", return_response)

        response = await requester.get()

        with pytest.raises(ResponseDataConversionError):
            response.as_list()
