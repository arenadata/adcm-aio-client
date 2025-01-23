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

from typing import Self

from asyncstdlib.functools import cached_property as async_cached_property
import pytest

from adcm_aio_client import Filter

pytestmark = [pytest.mark.asyncio]


class Dummy:
    def __init__(self: Self) -> None:
        self.counter = 0

    @async_cached_property
    async def func(self: Self) -> int:
        self.counter += 1

        return self.counter


async def test_async_cached_property() -> None:
    obj = Dummy()
    assert "func" not in obj.__dict__, "`func` key should not be cached yet"

    res = await obj.func
    assert res == 1
    assert "func" in obj.__dict__, "`func` key should be cached"

    res = await obj.func
    assert res == 1, "Cached value must be used"

    delattr(obj, "func")
    res = await obj.func
    assert res == 2, "Expected to execute func() again, increasing the counter"
    assert "func" in obj.__dict__


def test_filter_init() -> None:
    with pytest.raises(TypeError):
        Filter("name", "contains", "123")  # pyright: ignore[reportCallIssue]

    with pytest.raises(TypeError):
        Filter("name", op="contains", value="123")  # pyright: ignore[reportCallIssue]

    Filter(attr="name", op="contains", value="123")
