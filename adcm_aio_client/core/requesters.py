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

from typing import Literal, NamedTuple, Self, TypeAlias
from urllib.parse import urljoin

from typing_extensions import Protocol
import httpx

CredentialsDict: TypeAlias = dict[Literal["username", "password"], str]
AuthHeaderDict: TypeAlias = dict[Literal["Authorization"], str]


class _RequesterResponse(Protocol):
    response: httpx.Response

    def as_list(self: Self) -> list: ...

    def as_dict(self: Self) -> dict: ...


class Requester(Protocol):
    async def get(self: Self, path: str, query_params: dict) -> _RequesterResponse: ...

    async def post(self: Self, path: str, data: dict) -> _RequesterResponse: ...

    async def patch(self: Self, path: str, data: dict) -> _RequesterResponse: ...

    async def delete(self: Self, path: str) -> _RequesterResponse: ...


class Session(NamedTuple):  # TODO: client, credentials, def refresh()
    client: httpx.AsyncClient
    token: AuthHeaderDict | None

    @property
    def auth_header(self: Self) -> AuthHeaderDict:
        if self.token is None:
            return {}

        return {"Authorization": f"Token {self.token}"}


class RequesterResponse(NamedTuple):
    response: httpx.Response

    def as_list(self: Self) -> list: ...

    def as_dict(self: Self) -> dict: ...


class DefaultRequester(Requester):
    __slots__ = ("api_root", "_session")

    def __init__(self: Self, url: str, credentials: CredentialsDict | None = None) -> None:
        self.api_root = urljoin(url, "/api/v2/")

        if credentials is not None:
            self._session = self.login(credentials=credentials)
        else:
            self._session = Session(client=httpx.AsyncClient(), token=None)

    def login(self: Self, credentials: CredentialsDict) -> Session:
        response = httpx.post(url=urljoin(self.api_root, "token/"), data=credentials)
        response.raise_for_status()

        return Session(client=httpx.AsyncClient(), token=response.json()["token"])

    @property  # TODO: recreate on AuthError in self.request ??
    def session(self: Self) -> Session:
        return self._session

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
        headers = {**self.session.auth_header, **kwargs.pop("headers", {})}  # TODO: without auth headers

        response = await request_method(url, headers=headers, **kwargs)
        response.raise_for_status()

        return RequesterResponse(response=response)
