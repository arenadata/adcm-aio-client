from functools import cached_property
from typing import Self

import pytest

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


async def test_equality(queue_requester: QueueRequester) -> None:
    class ObjectA(InteractiveObject):
        def get_own_path(self: Self) -> Endpoint:
            return "not", "important"

    class ObjectB(InteractiveObject):
        def get_own_path(self: Self) -> Endpoint:
            return "not", "important"

    data_1 = {"id": 4, "name": "awesome"}
    data_2 = {"id": 5, "name": "best"}
    data_3 = {"id": 5, "name": "best"}
    data_4 = {"id": 4, "name": "awesome"}

    instance_1 = ObjectA(requester=queue_requester, data=data_1)
    instance_2 = ObjectA(requester=queue_requester, data=data_2)
    instance_3 = ObjectB(requester=queue_requester, data=data_3)
    instance_4 = ObjectB(requester=queue_requester, data=data_4)
    instance_5 = ObjectA(requester=queue_requester, data=data_4)

    assert (
        instance_1 != instance_2 and instance_2 != instance_3 and instance_3 != instance_1 and instance_4 != instance_1
    )
    assert instance_1 == instance_5
    assert instance_1 != (4, "awesome")
