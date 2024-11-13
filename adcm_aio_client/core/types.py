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
from typing import NamedTuple, Optional, Self, TypeAlias

from typing_extensions import Protocol


class AuthCredentials(NamedTuple):
    username: str
    password: str


AuthToken: TypeAlias = str
Cert: TypeAlias = str | tuple[str, Optional[str], Optional[str]] | None
Verify: TypeAlias = str | bool


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
