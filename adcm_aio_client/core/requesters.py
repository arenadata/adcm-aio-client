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
from contextlib import suppress
from dataclasses import asdict, dataclass
from functools import cached_property, wraps
from json.decoder import JSONDecodeError
from typing import Any, Awaitable, Callable, Coroutine, ParamSpec, Self, TypeAlias
from urllib.parse import urljoin

from typing_extensions import Protocol
import httpx

from adcm_aio_client.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    LoginError,
    NoCredentialsError,
    NotFoundError,
    ResponseDataConversionError,
    ResponseError,
    RetryRequestError,
    ServerError,
    UnauthorizedError,
    WrongCredentialsError,
)

Json: TypeAlias = Any
Params = ParamSpec("Params")
RequestFunc: TypeAlias = Callable[Params, Awaitable["HTTPXRequesterResponse"]]
DoRequestFunc: TypeAlias = Callable[Params, Awaitable[httpx.Response]]


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

    async def get(self: Self, *path: str | int, query_params: dict) -> RequesterResponse: ...

    async def post(self: Self, *path: str | int, data: dict) -> RequesterResponse: ...

    async def patch(self: Self, *path: str | int, data: dict) -> RequesterResponse: ...

    async def delete(self: Self, *path: str | int) -> RequesterResponse: ...


@dataclass(frozen=True)
class HTTPXRequesterResponse:
    response: httpx.Response

    def as_list(self: Self) -> list:
        if not isinstance(self.json_data, list):
            message = f"Expected a list, got {type(self.json_data)}"
            raise ResponseDataConversionError(message)

        return self.json_data

    def as_dict(self: Self) -> dict:
        if not isinstance(self.json_data, dict):
            message = f"Expected a dict, got {type(self.json_data)}"
            raise ResponseDataConversionError(message)

        return self.json_data

    @cached_property
    def json_data(self: Self) -> Json:
        try:
            data = self.response.json()
        except JSONDecodeError as e:
            message = "Response can't be parsed to json"
            raise ResponseDataConversionError(message) from e

        return data


STATUS_ERRORS_MAP = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    500: ServerError,
}


def convert_exceptions(func: DoRequestFunc) -> DoRequestFunc:
    @wraps(func)
    async def wrapper(*arg: Params.args, **kwargs: Params.kwargs) -> httpx.Response:
        response = await func(*arg, **kwargs)
        if response.status_code >= 300:
            raise STATUS_ERRORS_MAP.get(response.status_code, ResponseError)

        return response

    return wrapper


def retry_request(request_func: RequestFunc) -> RequestFunc:
    @wraps(request_func)
    async def wrapper(self: "DefaultRequester", *args: Params.args, **kwargs: Params.kwargs) -> HTTPXRequesterResponse:
        for _ in range(self.retries):
            try:
                response = await request_func(self, *args, **kwargs)
            except (UnauthorizedError, httpx.NetworkError, httpx.TransportError):
                await sleep(self.retry_interval)
                with suppress(httpx.NetworkError, httpx.TransportError):
                    await self.login(self._ensure_credentials())
            else:
                break
        else:
            message = f"Request failed in {self.retries} attempts"
            raise RetryRequestError(message)
        return response

    return wrapper


class DefaultRequester(Requester):
    __slots__ = ("_credentials", "api_root", "client", "retries", "retry_interval")

    def __init__(
        self: Self,
        base_url: str,
        root_path: str = "/api/v2/",
        timeout: float = 5.0,
        retries: int = 5,
        retry_interval: float = 5.0,
    ) -> None:
        self.retries = retries
        self.retry_interval = retry_interval
        self.api_root = self._make_url(root_path, base=base_url)
        self.client = httpx.AsyncClient(timeout=timeout)

    async def login(self: Self, credentials: Credentials) -> Self:
        login_url = self._make_url("login", base=self.api_root)

        try:
            response = await self._do_request(self.client.post(url=login_url, data=credentials.dict()))
        except UnauthorizedError as e:
            raise WrongCredentialsError from e

        if response.status_code != 200:
            message = f"Authentication error: {response.status_code} for url: {login_url}"
            raise LoginError(message)

        self._credentials = credentials
        return self

    async def get(self: Self, *path: str | int, query_params: dict | None = None) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.get, params=query_params or {})

    async def post(self: Self, *path: str | int, data: dict) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.post, data=data)

    async def patch(self: Self, *path: str | int, data: dict) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.patch, data=data)

    async def delete(self: Self, *path: str | int) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.delete)

    @retry_request
    async def request(self: Self, *path: str | int, method: Callable, **kwargs: dict) -> HTTPXRequesterResponse:
        url = self._make_url(*path, base=self.api_root)
        response = await self._do_request(method(url, **kwargs))

        return HTTPXRequesterResponse(response=response)

    @staticmethod
    def _make_url(*path: str | int, base: str) -> str:
        return urljoin(base, "/".join(map(str, (*path, ""))))

    @convert_exceptions
    async def _do_request(self: Self, request_coro: Coroutine[Any, Any, httpx.Response]) -> httpx.Response:
        return await request_coro

    def _ensure_credentials(self: Self) -> Credentials:
        if self._credentials is None:
            raise NoCredentialsError

        return self._credentials
