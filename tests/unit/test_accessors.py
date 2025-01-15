from collections.abc import AsyncGenerator, Callable
from typing import Any, Self

import pytest

from adcm_aio_client._filters import FilterBy, FilterByName, Filtering
from adcm_aio_client._types import Endpoint
from adcm_aio_client.errors import InvalidFilterError, MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects._accessors import (
    Accessor,
    NonPaginatedChildAccessor,
    PaginatedAccessor,
    PaginatedChildAccessor,
)
from adcm_aio_client.objects._base import InteractiveChildObject, InteractiveObject
from tests.unit.mocks.requesters import QueueRequester
from tests.unit.utils import n_entries_as_list

pytestmark = [pytest.mark.asyncio]


PAGE_SIZE = 50
no_validation = Filtering()


class _OwnPath:
    def get_own_path(self: Self) -> Endpoint:
        return ()


class Dummy(_OwnPath, InteractiveObject): ...


class DummyChild(_OwnPath, InteractiveChildObject): ...


class DummyPaginatedAccessor(PaginatedAccessor[Dummy]):
    class_type = Dummy
    filtering = no_validation


class DummyChildPaginatedAccessor(PaginatedChildAccessor[Dummy, DummyChild]):
    class_type = DummyChild
    filtering = no_validation


class DummyChildNonPaginatedAccessor(NonPaginatedChildAccessor[Dummy, DummyChild]):
    class_type = DummyChild
    filtering = no_validation


class DummyAccessorWithFilter(PaginatedAccessor[Dummy]):
    class_type = Dummy
    filtering = Filtering(FilterByName, FilterBy("custom", {"eq"}, Dummy))


def create_paginated_response(amount: int) -> dict:
    return {"results": [{} for _ in range(amount)]}


def extract_paginated_response_entries(data: dict) -> list:
    return data["results"]


def create_non_paginated_response(amount: int) -> list:
    return [{} for _ in range(amount)]


async def test_paginated(queue_requester: QueueRequester) -> None:
    requester = queue_requester
    accessor = DummyPaginatedAccessor(requester=requester, path=())

    await _test_paginated_accessor_common_methods(
        accessor=accessor,
        requester=requester,
        create_response=create_paginated_response,
        extract_entries=extract_paginated_response_entries,
        check_entry=lambda entry: isinstance(entry, Dummy),
    )


async def test_paginated_child(queue_requester: QueueRequester) -> None:
    requester = queue_requester
    parent = Dummy(requester=requester, data={})
    accessor = DummyChildPaginatedAccessor(requester=requester, path=(), parent=parent)

    await _test_paginated_accessor_common_methods(
        accessor=accessor,
        requester=requester,
        create_response=create_paginated_response,
        extract_entries=extract_paginated_response_entries,
        check_entry=lambda entry: isinstance(entry, DummyChild) and entry._parent is parent,
    )


async def test_non_paginated_child(queue_requester: QueueRequester) -> None:
    requester = queue_requester
    parent = Dummy(requester=requester, data={})
    accessor = DummyChildNonPaginatedAccessor(requester=requester, path=(), parent=parent)
    create_response = create_non_paginated_response
    check_entry = lambda entry: isinstance(entry, DummyChild) and entry._parent is parent  # noqa: E731

    response_sequence = (create_response(PAGE_SIZE), create_response(4), create_response(0))
    amount_of_entries = len(response_sequence[0])

    # get

    requester.flush().queue_responses(create_response(1))
    result = await accessor.get()

    assert check_entry(result)

    requester.flush().queue_responses(create_response(0))

    with pytest.raises(ObjectDoesNotExistError):
        await accessor.get()
    requester.flush().queue_responses(create_response(2))

    with pytest.raises(MultipleObjectsReturnedError):
        await accessor.get()

    # get or none

    requester.flush().queue_responses(create_response(1))
    result = await accessor.get_or_none()

    assert check_entry(result)

    requester.flush().queue_responses(create_response(0))
    result = await accessor.get_or_none()

    assert result is None

    requester.flush().queue_responses(create_response(2))

    with pytest.raises(MultipleObjectsReturnedError):
        await accessor.get_or_none()

    # list

    requester.flush().queue_responses(*response_sequence)
    result = await accessor.list()

    assert isinstance(result, list)
    assert len(result) == PAGE_SIZE
    assert all(map(check_entry, result))

    assert len(requester.queue) == len(response_sequence) - 1

    # all

    requester.flush().queue_responses(*response_sequence)
    result = await accessor.all()

    assert isinstance(result, list)
    assert len(result) == amount_of_entries
    assert all(map(check_entry, result))

    assert len(requester.queue) == len(response_sequence) - 1

    # filter (with no args is the same as all)

    requester.flush().queue_responses(*response_sequence)
    result = await accessor.filter()

    assert isinstance(result, list)
    assert len(result) == amount_of_entries
    assert all(map(check_entry, result))

    assert len(requester.queue) == len(response_sequence) - 1

    # iter

    requester.flush().queue_responses(*response_sequence)
    result = accessor.iter()

    # see no requests made at first
    assert len(requester.queue) == len(response_sequence)
    assert isinstance(result, AsyncGenerator)

    all_entries = [entry async for entry in result]
    assert len(all_entries) == amount_of_entries
    assert all(map(check_entry, all_entries))

    # see 1 "pages" read, because it's not paginated
    assert len(requester.queue) == len(response_sequence) - 1


async def _test_paginated_accessor_common_methods[T: dict | list](
    accessor: Accessor,
    requester: QueueRequester,
    create_response: Callable[[int], T],
    extract_entries: Callable[[T], list],
    check_entry: Callable[[Any], bool],
) -> None:
    response_sequence = (create_response(PAGE_SIZE), create_response(PAGE_SIZE), create_response(4), create_response(0))
    amount_of_all_entries = sum(map(len, map(extract_entries, response_sequence)))

    # get

    requester.flush().queue_responses(create_response(1))
    result = await accessor.get()

    assert check_entry(result)

    requester.flush().queue_responses(create_response(0))

    with pytest.raises(ObjectDoesNotExistError):
        await accessor.get()

    requester.flush().queue_responses(create_response(2))

    with pytest.raises(MultipleObjectsReturnedError):
        await accessor.get()

    # get or none

    requester.flush().queue_responses(create_response(1))
    result = await accessor.get_or_none()

    assert check_entry(result)

    requester.flush().queue_responses(create_response(0))
    result = await accessor.get_or_none()

    assert result is None

    requester.flush().queue_responses(create_response(2))

    with pytest.raises(MultipleObjectsReturnedError):
        await accessor.get_or_none()

    # list

    requester.flush().queue_responses(*response_sequence)
    result = await accessor.list()

    assert isinstance(result, list)
    assert len(result) == PAGE_SIZE
    assert all(map(check_entry, result))
    assert len(requester.queue) == len(response_sequence) - 1

    # all

    requester.flush().queue_responses(*response_sequence)
    result = await accessor.all()

    assert isinstance(result, list)
    assert len(result) == amount_of_all_entries
    assert all(map(check_entry, result))

    # filter (with no args is the same as all)

    requester.flush().queue_responses(*response_sequence)
    result = await accessor.filter()

    assert isinstance(result, list)
    assert len(result) == amount_of_all_entries
    assert all(map(check_entry, result))

    # iter

    requester.flush().queue_responses(*response_sequence)
    result = accessor.iter()

    # see no requests made at first
    assert len(requester.queue) == len(response_sequence)
    assert isinstance(result, AsyncGenerator)

    n = PAGE_SIZE + 1
    first_entries = await n_entries_as_list(result, n=n)
    assert len(first_entries) == n

    # see 2 "pages" read
    assert len(requester.queue) == len(response_sequence) - 2

    rest_entries = [i async for i in result]
    assert len(rest_entries) == amount_of_all_entries - n
    assert all(map(check_entry, (*first_entries, *rest_entries)))

    # empty page was not read (because previous page < PAGE_SIZE)
    assert requester.queue.popleft()["results"] == []  # pyright: ignore[reportCallIssue, reportArgumentType]

    # now all results are read
    assert len(requester.queue) == 0


async def test_filter_validation(queue_requester: QueueRequester) -> None:
    accessor = DummyAccessorWithFilter(requester=queue_requester, path=())

    with pytest.raises(InvalidFilterError, match="by notexist is not allowed"):
        await accessor.get(notexist__eq="sd")

    with pytest.raises(InvalidFilterError, match="Operation in is not allowed"):
        await accessor.get(custom__in=["sd"])

    with pytest.raises(InvalidFilterError, match="At least one entry is not"):
        await accessor.get(name__iin=("sdlfkj", 1))

    with pytest.raises(InvalidFilterError, match=f"1 is not {str}"):
        await accessor.get(name__eq=1)

    with pytest.raises(InvalidFilterError, match="Multiple values expected for exclude"):
        await accessor.get(name__exclude="sd")

    with pytest.raises(InvalidFilterError, match="Collection for filter shouldn't be empty"):
        await accessor.get(name__exclude=[])

    with pytest.raises(InvalidFilterError, match="Only one value is expected for icontains"):
        await accessor.get(name__icontains={"sldkfj"})
