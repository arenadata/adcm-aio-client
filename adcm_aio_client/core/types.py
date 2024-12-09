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

from dataclasses import asdict, dataclass
from typing import Optional, Protocol, Self

# Init / Authorization

type AuthToken = str
type Cert = str | tuple[str, Optional[str], Optional[str]] | None
type Verify = str | bool


@dataclass(slots=True, frozen=True)
class Credentials:
    username: str
    password: str

    def dict(self: Self) -> dict:
        return asdict(self)

    def __repr__(self: Self) -> str:
        return f"{self.username}'s credentials"


# Requests

type PathPart = str | int
type Endpoint = tuple[PathPart, ...]

type QueryParameters = dict


class RequesterResponse(Protocol):
    def as_list(self: Self) -> list: ...

    def as_dict(self: Self) -> dict: ...


class Requester(Protocol):
    async def login(self: Self, credentials: Credentials) -> Self: ...

    async def get(self: Self, *path: PathPart, query: QueryParameters | None = None) -> RequesterResponse: ...

    async def post(self: Self, *path: PathPart, data: dict) -> RequesterResponse: ...

    async def patch(self: Self, *path: PathPart, data: dict) -> RequesterResponse: ...

    async def delete(self: Self, *path: PathPart) -> RequesterResponse: ...


# Objects


class WithRequester(Protocol):
    _requester: Requester


class AwareOfOwnPath(Protocol):
    def get_own_path(self: Self) -> Endpoint: ...
