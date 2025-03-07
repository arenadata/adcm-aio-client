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

from functools import cached_property
from typing import Self

import pytest

from adcm_aio_client._types import Endpoint
from adcm_aio_client.objects._base import InteractiveObject
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

    class ObjectC:
        class ObjectA(InteractiveObject):
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
    instance_6 = ObjectC

    assert (
        instance_1 != instance_2 and instance_2 != instance_3 and instance_3 != instance_1 and instance_4 != instance_1
    )
    assert instance_1 != instance_6.ObjectA(requester=queue_requester, data=data_1)
    assert instance_1 == instance_5
    assert instance_1 != (4, "awesome")
