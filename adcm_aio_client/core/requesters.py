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
from abc import ABC, abstractmethod
from asyncio import sleep
from contextlib import suppress
from dataclasses import dataclass
from functools import wraps
from json.decoder import JSONDecodeError
from typing import Any, Awaitable, Callable, Coroutine, ParamSpec, Self, TypeAlias
from urllib.parse import urljoin

import httpx

from adcm_aio_client.core.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    LoginError,
    LogoutError,
    NoCredentialsError,
    NotFoundError,
    OperationError,
    ResponseDataConversionError,
    ResponseError,
    RetryRequestError,
    ServerError,
    UnauthorizedError,
    WrongCredentialsError,
)
from adcm_aio_client.core.types import Credentials, PathPart, QueryParameters, Requester, RetryPolicy, URLStr

Json: TypeAlias = Any
Params = ParamSpec("Params")
RequestFunc: TypeAlias = Callable[Params, Awaitable["HTTPXRequesterResponse"]]
DoRequestFunc: TypeAlias = Callable[Params, Awaitable[httpx.Response]]


@dataclass(slots=True)
class HTTPXRequesterResponse:
    response: httpx.Response
    _json_data: Json | None = None

    def as_list(self: Self) -> list:
        if not isinstance(data := self._get_json_data(), list):
            message = f"Expected a list, got {type(data)}"
            raise ResponseDataConversionError(message)

        return data

    def as_dict(self: Self) -> dict:
        if not isinstance(data := self._get_json_data(), dict):
            message = f"Expected a dict, got {type(data)}"
            raise ResponseDataConversionError(message)

        return data

    def _get_json_data(self: Self) -> Json:
        if self._json_data is not None:
            return self._json_data

        try:
            data = self.response.json()
        except JSONDecodeError as e:
            message = "Response can't be parsed to json"
            raise ResponseDataConversionError(message) from e

        self._json_data = data

        return self._json_data


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
            error_cls = STATUS_ERRORS_MAP.get(response.status_code, ResponseError)
            # not safe, because can be not json
            try:
                message = response.json()
            except JSONDecodeError:
                message = f"Request failed with > 300 response code: {response.content.decode('utf-8')}"
            raise error_cls(message)

        return response

    return wrapper


def retry_request(request_func: RequestFunc) -> RequestFunc:
    @wraps(request_func)
    async def wrapper(self: "DefaultRequester", *args: Params.args, **kwargs: Params.kwargs) -> HTTPXRequesterResponse:
        retries = self._retries
        for attempt in range(retries.attempts):
            try:
                response = await request_func(self, *args, **kwargs)
            except (UnauthorizedError, httpx.NetworkError, httpx.TransportError):
                if attempt >= retries.attempts - 1:
                    continue

                await sleep(retries.interval)

                with suppress(httpx.NetworkError, httpx.TransportError):
                    await self.login(self._ensure_credentials())
            else:
                break
        else:
            message = f"Request failed in {retries.interval} attempts"
            raise RetryRequestError(message)

        return response

    return wrapper


class DefaultRequester(Requester):
    __slots__ = ("_credentials", "_client", "_retries", "_prefix")

    def __init__(self: Self, http_client: httpx.AsyncClient, retries: RetryPolicy) -> None:
        self._retries = retries
        self._client = http_client
        self._prefix = "/api/v2/"
        self._credentials = None

    @property
    def client(self: Self) -> httpx.AsyncClient:
        return self._client

    async def login(self: Self, credentials: Credentials) -> Self:
        login_url = self._make_url("login")

        try:
            response = await self._do_request(self.client.post(url=login_url, data=credentials.dict()))
        except UnauthorizedError as e:
            message = f"Login to ADCM at {self.client.base_url} has failed for user {credentials.username} most likely due to incorrect credentials"
            raise WrongCredentialsError(message) from e
        except ResponseError as e:
            message = f"Login to ADCM at {self.client.base_url} has failed for user {credentials.username}: {e}"
            raise LoginError(message) from e

        self._credentials = credentials
        self.client.headers["X-CSRFToken"] = response.cookies["csrftoken"]

        return self

    async def logout(self: Self) -> Self:
        logout_url = self._make_url("logout")

        try:
            request_coro = self.client.post(url=logout_url, data={})
            await self._do_request(request_coro)
        except ResponseError as e:
            message = f"Logout from ADCM at {self.client.base_url} has failed"
            raise LogoutError(message) from e

        self.client.headers.pop("X-CSRFToken", None)

        return self

    async def get(self: Self, *path: PathPart, query: QueryParameters | None = None) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.get, params=query or {})

    async def post_files(self: Self, *path: PathPart, files: dict) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.post, files=files)

    async def post(self: Self, *path: PathPart, data: dict | list) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.post, json=data)

    async def patch(self: Self, *path: PathPart, data: dict | list) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.patch, json=data)

    async def delete(self: Self, *path: PathPart) -> HTTPXRequesterResponse:
        return await self.request(*path, method=self.client.delete)

    @retry_request
    async def request(self: Self, *path: PathPart, method: Callable, **kwargs: dict) -> HTTPXRequesterResponse:
        url = self._make_url(*path)
        response = await self._do_request(method(url, **kwargs))

        return HTTPXRequesterResponse(response=response)

    def _make_url(self, *path: PathPart) -> str:
        return urljoin(self._prefix, "/".join(map(str, (*path, ""))))

    @convert_exceptions
    async def _do_request(self: Self, request_coro: Coroutine[Any, Any, httpx.Response]) -> httpx.Response:
        return await request_coro

    def _ensure_credentials(self: Self) -> Credentials:
        if self._credentials is None:
            raise NoCredentialsError

        return self._credentials


class BundleRetrieverInterface(ABC):
    @abstractmethod
    async def download_external_bundle(self: Self, url: URLStr) -> bytes:
        pass


class BundleRetriever(BundleRetrieverInterface):
    async def download_external_bundle(self: Self, url: URLStr) -> bytes:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
        except ValueError as err:
            raise OperationError(f"Failed to download the bundle {url}") from err
        except httpx.HTTPStatusError as err:
            raise OperationError(f"HTTP error occurred: {err}") from err
