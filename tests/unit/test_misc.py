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
