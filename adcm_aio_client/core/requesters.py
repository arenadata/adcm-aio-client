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

from typing import AsyncGenerator, Self

from typing_extensions import Protocol


class RequesterResponse(Protocol):
    def as_list(self: Self) -> list: ...

    def as_dict(self: Self) -> dict: ...


class Requester(Protocol):
    async def get(self: Self, path: str, query_params: dict) -> AsyncGenerator[RequesterResponse]: ...

    async def post(self: Self, path: str, data: dict) -> AsyncGenerator[RequesterResponse]: ...

    async def patch(self: Self, path: str, data: dict) -> AsyncGenerator[RequesterResponse]: ...

    async def delete(self: Self, path: str) -> AsyncGenerator[RequesterResponse]: ...


class Session: ...


class DefaultRequester(Requester):
    def __init__(self: Self) -> None: ...

    @property
    async def session(self: Self) -> AsyncGenerator[Session]: ...
