from typing import Any, AsyncGenerator, Awaitable, Callable, Self

import pytest

from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.objects._accessors import (
    Accessor,
    NonPaginatedChildAccessor,
    PaginatedAccessor,
    PaginatedChildAccessor,
)
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.types import Endpoint
from tests.unit.mocks.requesters import QueueRequester
from tests.unit.utils import n_entries_as_list

pytestmark = [pytest.mark.asyncio]


class _OwnPath:
    def get_own_path(self: Self) -> Endpoint:
        return ()


class Dummy(_OwnPath, InteractiveObject): ...


class DummyChild(_OwnPath, InteractiveChildObject): ...


class DummyPaginatedAccessor(PaginatedAccessor[Dummy, None]):
    class_type = Dummy


class DummyChildPaginatedAccessor(PaginatedChildAccessor[Dummy, DummyChild, None]):
    class_type = DummyChild


class DummyChildNonPaginatedAccessor(NonPaginatedChildAccessor[Dummy, DummyChild, None]):
    class_type = DummyChild


def create_paginated_response(amount: int) -> dict:
    return {"results": [{} for _ in range(amount)]}


def extract_paginated_response_entries(data: dict) -> list:
    return data["results"]


def create_non_paginated_response(amount: int) -> list:
    return [{} for _ in range(amount)]


def extract_non_paginated_response_entries(data: list) -> list:
    return data


async def test_paginated(queue_requester: QueueRequester) -> None:
    requester = queue_requester
    accessor = DummyPaginatedAccessor(requester=requester, path=())

    await _test_accessor_common_methods(
        accessor=accessor,
        requester=requester,
        create_response=create_paginated_response,
        extract_entries=extract_paginated_response_entries,
        check_entry=lambda entry: isinstance(entry, Dummy),
        check_iter_method=_check_iter_for_paginated_accessor,
    )


async def test_paginated_child(queue_requester: QueueRequester) -> None:
    requester = queue_requester
    parent = Dummy(requester=requester, data={})
    accessor = DummyChildPaginatedAccessor(requester=requester, path=(), parent=parent)

    await _test_accessor_common_methods(
        accessor=accessor,
        requester=requester,
        create_response=create_paginated_response,
        extract_entries=extract_paginated_response_entries,
        check_entry=lambda entry: isinstance(entry, DummyChild) and entry._parent is parent,
        check_iter_method=_check_iter_for_paginated_accessor,
    )


async def test_non_paginated_child(queue_requester: QueueRequester) -> None:
    requester = queue_requester
    parent = Dummy(requester=requester, data={})
    accessor = DummyChildNonPaginatedAccessor(requester=requester, path=(), parent=parent)

    await _test_accessor_common_methods(
        accessor=accessor,
        requester=requester,
        create_response=create_non_paginated_response,
        extract_entries=extract_non_paginated_response_entries,
        check_entry=lambda entry: isinstance(entry, DummyChild) and entry._parent is parent,
        check_iter_method=_check_iter_for_non_paginated_accessor,
    )


async def _test_accessor_common_methods[T: dict | list](
    accessor: Accessor,
    requester: QueueRequester,
    create_response: Callable[[int], T],
    extract_entries: Callable[[T], list],
    check_entry: Callable[[Any], bool],
    check_iter_method: Callable[..., Awaitable],
) -> None:
    response_sequence = (create_response(10), create_response(10), create_response(4), create_response(0))
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
    assert len(result) == 10
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

    await check_iter_method(
        accessor=accessor,
        requester=requester,
        create_response=create_response,
        extract_entries=extract_entries,
        check_entry=check_entry,
    )


async def _check_iter_for_paginated_accessor[T: dict | list](
    accessor: Accessor,
    requester: QueueRequester,
    create_response: Callable[[int], T],
    extract_entries: Callable[[T], list],
    check_entry: Callable[[Any], bool],
) -> None:
    response_sequence = (create_response(10), create_response(10), create_response(4), create_response(0))
    amount_of_all_entries = sum(map(len, map(extract_entries, response_sequence)))

    requester.flush().queue_responses(*response_sequence)
    result = accessor.iter()

    # see no requests made at first
    assert len(requester.queue) == len(response_sequence)
    assert isinstance(result, AsyncGenerator)

    n = 11
    first_entries = await n_entries_as_list(result, n=n)
    assert len(first_entries) == n

    # see 2 "pages" read
    assert len(requester.queue) == len(response_sequence) - 2

    rest_entries = [i async for i in result]
    assert len(rest_entries) == amount_of_all_entries - n
    assert all(map(check_entry, (*first_entries, *rest_entries)))

    # now all results are read
    assert len(requester.queue) == 0


async def _check_iter_for_non_paginated_accessor[T: dict | list](
    accessor: Accessor,
    requester: QueueRequester,
    create_response: Callable[[int], T],
    extract_entries: Callable[[T], list],
    check_entry: Callable[[Any], bool],
) -> None:
    response_sequence = (create_response(10), create_response(10), create_response(4), create_response(0))
    records_in_first_response = len(extract_entries(response_sequence[0]))

    requester.flush().queue_responses(*response_sequence)
    result = accessor.iter()

    # see no requests made at first
    assert len(requester.queue) == len(response_sequence)
    assert isinstance(result, AsyncGenerator)

    all_entries = [entry async for entry in result]
    assert len(all_entries) == records_in_first_response
    assert all(map(check_entry, all_entries))

    # see 1 "pages" read, because it's not paginated
    assert len(requester.queue) == len(response_sequence) - 1
