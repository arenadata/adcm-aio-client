import pytest

from functools import cached_property
from typing import Self
from adcm_aio_client.core.objects._base import InteractiveObject
from adcm_aio_client.core.types import Endpoint
from tests.unit.mocks.requesters import QueueRequester

pytestmark = [pytest.mark.asyncio]

async def test_cache_cleaning(queue_requester: QueueRequester) -> None:
    class ObjectA(InteractiveObject):
        def get_own_path(self: Self) -> Endpoint:
            return "not", "important"

        @property
        def plain(self: Self) -> str:
            return self._data["name"]

        @cached_property
        def complex(self: Self) -> str:
            return self._data["name"]

    data_1 = {"id": 4, "name": "awesome"}
    data_2 = {"id": 4, "name": "best"}

    instance = ObjectA(requester=queue_requester, data=data_1)

    assert instance.plain == instance.complex
    assert instance.complex == data_1["name"]

    queue_requester.queue_responses(data_2)

    await instance.refresh()

    assert instance.plain == instance.complex
    assert instance.complex == data_2["name"]



