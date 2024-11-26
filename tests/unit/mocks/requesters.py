from collections import deque
from dataclasses import dataclass, field
from typing import Self

from adcm_aio_client.core.errors import ResponseDataConversionError
from adcm_aio_client.core.types import Credentials, PathPart, QueryParameters, Requester, RequesterResponse

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


@dataclass()
class QueueRequester(Requester):
    queue: deque[FakeResponseData] = field(default_factory=deque)

    async def login(self: Self, credentials: Credentials) -> Self:
        _ = credentials
        return self

    async def get(self: Self, *path: PathPart, query: QueryParameters | None = None) -> RequesterResponse:
        _ = path, query
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
