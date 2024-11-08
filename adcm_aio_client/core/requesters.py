# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from asyncio import sleep
from dataclasses import asdict, dataclass
from functools import wraps
from json.decoder import JSONDecodeError
from typing import Any, Callable, Coroutine, Iterable, Self, TypeAlias
from urllib.parse import urljoin

from typing_extensions import Protocol
import httpx

from adcm_aio_client.core.errors import (
    BadRequestError,
    ConflictError,
    LoginError,
    NoCredentialsError,
    NotFoundError,
    ReconnectError,
    RequesterResponseError,
    ResponseError,
    ServerError,
    UnauthorizedError,
    WrongCredentialsError,
)

Json: TypeAlias = Any


@dataclass(slots=True, frozen=True)
class Credentials:
    username: str
    password: str

    def dict(self: Self) -> dict:
        return asdict(self)

    def __repr__(self: Self) -> str:
        return f"{self.username}'s credentials"


class RequesterResponse(Protocol):
    def as_list(self: Self) -> list: ...

    def as_dict(self: Self) -> dict: ...


class Requester(Protocol):
    async def login(self: Self, credentials: Credentials) -> Self: ...

    async def get(self: Self, path: str, query_params: dict) -> RequesterResponse: ...

    async def post(self: Self, path: str, data: dict) -> RequesterResponse: ...

    async def patch(self: Self, path: str, data: dict) -> RequesterResponse: ...

    async def delete(self: Self, path: str) -> RequesterResponse: ...


@dataclass(slots=True, frozen=True)
class HTTPXRequesterResponse:
    response: httpx.Response

    def as_list(self: Self) -> list:
        if not isinstance(data := self._prepare_json_response(), list):
            message = f"Expected a list, got {type(data)}"
            raise RequesterResponseError(message)

        return data

    def as_dict(self: Self) -> dict:
        if not isinstance(data := self._prepare_json_response(), dict):
            message = f"Expected a dict, got {type(data)}"
            raise RequesterResponseError(message)

        return data

    def _prepare_json_response(self: Self) -> Json:
        try:
            data = self.response.json()
        except JSONDecodeError as e:
            message = "Response can't be parsed to json"
            raise RequesterResponseError(message) from e

        if "results" in data:
            data = data["results"]

        return data


def _get_error_class(status_code: int) -> type[ResponseError]:
    first_digit = status_code // 100
    match first_digit:
        case 5:
            return ServerError
        case 4:
            match status_code:
                case 400:
                    return BadRequestError
                case 401:
                    return UnauthorizedError
                case 404:
                    return NotFoundError
                case 409:
                    return ConflictError

    return ResponseError


def convert_exceptions(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*arg: Iterable, **kwargs: dict) -> httpx.Response:
        response = await func(*arg, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise _get_error_class(status_code=response.status_code) from e

        return response

    return wrapper


class DefaultRequester(Requester):
    __slots__ = ("api_root", "client", "retries", "retry_interval", "_credentials")

    def __init__(self: Self, url: str, retries: int = 5, retry_interval: float = 5.0) -> None:
        self.retries = retries
        self.retry_interval = retry_interval
        self.api_root = urljoin(url, "/api/v2/")
        self.client = httpx.AsyncClient()

    async def login(self: Self, credentials: Credentials) -> Self:
        login_url = urljoin(self.api_root, "login/")

        try:
            response = await self._do_request(self.client.post(url=login_url, data=credentials.dict()))
        except UnauthorizedError as e:
            raise WrongCredentialsError from e

        if response.status_code != 200:
            message = f"Authentication error: {response.status_code} for url: {login_url}"
            raise LoginError(message)

        self._credentials = credentials
        return self

    async def get(self: Self, path: str, query_params: dict | None = None) -> HTTPXRequesterResponse:
        return await self.request(method="get", path=path, params=query_params or {})

    async def post(self: Self, path: str, data: dict, **kwargs: dict) -> HTTPXRequesterResponse:
        return await self.request(method="post", path=path, data=data, **kwargs)

    async def patch(self: Self, path: str, data: dict, **kwargs: dict) -> HTTPXRequesterResponse:
        return await self.request(method="patch", path=path, data=data, **kwargs)

    async def delete(self: Self, path: str, **kwargs: dict) -> HTTPXRequesterResponse:
        return await self.request(method="delete", path=path, **kwargs)

    async def request(self: Self, method: str, path: str, **kwargs: dict) -> HTTPXRequesterResponse:
        url = urljoin(self.api_root, f"{path}/" if not path.endswith("/") else path)
        request_method = getattr(self.client, method.lower())

        try:
            response = await self._do_request(request_method(url, headers=kwargs.pop("headers", {}), **kwargs))
        except UnauthorizedError:
            await self._reconnect()
            response = await self._do_request(request_method(url, headers=kwargs.pop("headers", {}), **kwargs))

        return HTTPXRequesterResponse(response=response)

    @convert_exceptions
    async def _do_request(self: Self, request_coro: Coroutine[Any, Any, httpx.Response]) -> httpx.Response:
        return await request_coro

    async def _reconnect(self: Self) -> None:
        credentials = self._ensure_credentials()

        for _ in range(self.retries):
            try:
                await self.login(credentials=credentials)
                break
            except (httpx.NetworkError, httpx.TransportError):
                await sleep(delay=self.retry_interval)
        else:
            message = f"Can't reconnect in {self.retries} attempts"
            raise ReconnectError(message)

    def _ensure_credentials(self: Self) -> Credentials:
        if self._credentials is None:
            raise NoCredentialsError

        return self._credentials
