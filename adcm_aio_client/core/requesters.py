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

from asyncio import get_event_loop
from dataclasses import asdict, dataclass
from json.decoder import JSONDecodeError
from typing import Any, NamedTuple, Self, TypeAlias
from urllib.parse import urljoin

from typing_extensions import Protocol
import httpx

Json: TypeAlias = Any


class RequesterError(Exception):
    pass


class SessionError(RequesterError):
    pass


class ResponseError(RequesterError):
    pass


class UnauthorizedResponseError(ResponseError):
    pass


class _RequesterResponse(Protocol):  # TODO: name
    response: httpx.Response

    def as_list(self: Self) -> list: ...

    def as_dict(self: Self) -> dict: ...


class Requester(Protocol):
    async def get(self: Self, path: str, query_params: dict) -> _RequesterResponse: ...

    async def post(self: Self, path: str, data: dict) -> _RequesterResponse: ...

    async def patch(self: Self, path: str, data: dict) -> _RequesterResponse: ...

    async def delete(self: Self, path: str) -> _RequesterResponse: ...


@dataclass(slots=True, frozen=True)
class Credentials:
    username: str
    password: str

    def dict(self: Self) -> dict:
        return asdict(self)

    def __repr__(self: Self) -> str:
        return f"{self.username}'s credentials"


class Session:
    __slots__ = ("api_root", "client", "_credentials")

    def __init__(self: Self, api_root: str, credentials: Credentials | None) -> None:
        self.api_root = api_root
        self.client = httpx.AsyncClient()
        if credentials is not None:
            self._credentials = credentials
            self.refresh()

    @property
    def refreshable(self: Self) -> bool:
        return self._credentials is not None

    def refresh(self: Self) -> None:
        if not self.refreshable:
            message = "Can't refresh session without user credentials"
            raise SessionError(message)

        login_url = urljoin(self.api_root, "login/")
        response = get_event_loop().run_until_complete(self.client.post(url=login_url, data=self._credentials.dict()))

        if response.status_code != 200:
            message = f"Authentication error: {response.status_code} for url: {login_url}"
            raise SessionError(message)


class RequesterResponse(NamedTuple):
    response: httpx.Response

    def as_list(self: Self) -> list:
        if not isinstance(data := self._prepare_json_response(), list):
            message = f"Expected a list, got {type(data)}"
            raise ResponseError(message)

        return data

    def as_dict(self: Self) -> dict:
        if not isinstance(data := self._prepare_json_response(), dict):
            message = f"Expected a dict, got {type(data)}"
            raise ResponseError(message)

        return data

    def _prepare_json_response(self: Self) -> Json:
        try:
            data = self.response.json()
        except JSONDecodeError as e:
            message = "Response can't be parsed to json"
            raise ResponseError(message) from e

        if "results" in data:
            data = data["results"]

        return data


class DefaultRequester(Requester):
    __slots__ = ("api_root", "session")

    def __init__(self: Self, url: str, credentials: Credentials | None = None) -> None:
        self.api_root = urljoin(url, "/api/v2/")
        self.session = Session(api_root=self.api_root, credentials=credentials)

    async def get(self: Self, path: str, query_params: dict | None = None) -> RequesterResponse:
        return await self.request(method="get", path=path, params=query_params or {})

    async def post(self: Self, path: str, data: dict, **kwargs: dict) -> RequesterResponse:
        return await self.request(method="post", path=path, data=data, **kwargs)

    async def patch(self: Self, path: str, data: dict, **kwargs: dict) -> RequesterResponse:
        return await self.request(method="patch", path=path, data=data, **kwargs)

    async def delete(self: Self, path: str, **kwargs: dict) -> RequesterResponse:
        return await self.request(method="delete", path=path, **kwargs)

    async def request(self: Self, method: str, path: str, **kwargs: dict) -> RequesterResponse:
        request_method = getattr(self.session.client, method.lower())
        url = urljoin(self.api_root, path)
        response = await request_method(url, headers=kwargs.pop("headers", {}), **kwargs)
        # TODO: self.session.refresh() on AuthErrors
        response.raise_for_status()

        return RequesterResponse(response=response)
