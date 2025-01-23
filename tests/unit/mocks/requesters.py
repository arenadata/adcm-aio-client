# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import deque
from dataclasses import dataclass, field
from typing import Self

from adcm_aio_client._types import Credentials, PathPart, QueryParameters, Requester, RequesterResponse
from adcm_aio_client.errors import ResponseDataConversionError

type FakeResponseData = dict | list


@dataclass(slots=True)
class QueueResponse(RequesterResponse):
    data: FakeResponseData

    def as_list(self: Self) -> list:
        if not isinstance(data := self.data, list):
            message = f"Expected a list, got {type(data)}"
            raise ResponseDataConversionError(message)

        return data

    def as_dict(self: Self) -> dict:
        if not isinstance(data := self.data, dict):
            message = f"Expected a dict, got {type(data)}"
            raise ResponseDataConversionError(message)

        return data

    def get_status_code(self: Self) -> int:
        return 200


@dataclass()
class QueueRequester(Requester):
    queue: deque[FakeResponseData] = field(default_factory=deque)

    async def login(self: Self, credentials: Credentials) -> Self:
        _ = credentials
        return self

    async def get(self: Self, *path: PathPart, query: QueryParameters | None = None) -> RequesterResponse:
        _ = path, query
        return self._return_next_response()

    async def post_files(self: Self, *path: PathPart, files: dict | list) -> RequesterResponse:
        _ = path, files
        return self._return_next_response()

    async def post(self: Self, *path: PathPart, data: dict | list) -> RequesterResponse:
        _ = path, data
        return self._return_next_response()

    async def patch(self: Self, *path: PathPart, data: dict | list) -> RequesterResponse:
        _ = path, data
        return self._return_next_response()

    async def delete(self: Self, *path: PathPart) -> RequesterResponse:
        _ = path
        return self._return_next_response()

    # specifics

    def queue_responses(self: Self, *responses: FakeResponseData) -> Self:
        self.queue.extend(responses)
        return self

    def flush(self: Self) -> Self:
        self.queue.clear()
        return self

    def _return_next_response(self: Self) -> RequesterResponse:
        next_response = self.queue.popleft()
        return QueueResponse(data=next_response)
