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

from collections import deque
from dataclasses import dataclass
from typing import Generator, Iterable, Protocol, Self

from adcm_aio_client.core.errors import InvalidFilterError
from adcm_aio_client.core.objects._base import InteractiveObject
from adcm_aio_client.core.types import QueryParameters

# Filters
EQUAL_OPERATIONS = frozenset(("eq", "ieq"))
MULTI_OPERATIONS = frozenset(("in", "iin", "exclude", "iexclude"))


COMMON_OPERATIONS = frozenset(("eq", "ne", "in", "exclude"))
ALL_OPERATIONS = frozenset(("contains", "icontains", *COMMON_OPERATIONS, *tuple(f"i{op}" for op in COMMON_OPERATIONS)))

type FilterSingleValue = str | int | InteractiveObject
type FilterValue = FilterSingleValue | Iterable[FilterSingleValue]


@dataclass(slots=True)
class Filter:
    attr: str
    op: str
    value: FilterValue


class FilterValidator(Protocol):
    def __call__(self, filter_: Filter) -> None: ...  # noqa: ANN101


@dataclass(slots=True, frozen=True)
class FilterBy:
    attr: str
    operations: set[str] | frozenset[str] | tuple[str, ...]
    single_input: type


class Filtering(FilterValidator):
    def __init__(self: Self, *allowed: FilterBy) -> None:
        self._allowed = {entry.attr: entry for entry in allowed}

    def __call__(self: Self, filter_: Filter) -> None:
        allowed_filter = self._allowed.get(filter_.attr)
        if not allowed_filter:
            message = f"Filter by {filter_.attr} is not allowed. Allowed: {', '.join(self._allowed)}"
            raise InvalidFilterError(message)

        if filter_.op not in allowed_filter.operations:
            message = f"Operation {filter_.op} is not allowed. Allowed: {', '.join(sorted(allowed_filter.operations))}"
            raise InvalidFilterError(message)

        # we don't want to empty generator here
        if isinstance(filter_.value, Generator):
            filter_.value = tuple(filter_.value)

        expected_type = allowed_filter.single_input
        if isinstance(filter_.value, Iterable):
            if not all(isinstance(entry, expected_type) for entry in filter_.value):
                message = f"At least one entry is not {expected_type}: {filter_.value}"
                raise InvalidFilterError(message)
        else:
            if not isinstance(filter_.value, expected_type):
                message = f"Value {filter_.value} is not {expected_type}"
                raise InvalidFilterError(message)


FilterByName = FilterBy("name", ALL_OPERATIONS, str)
FilterByDisplayName = FilterBy("display_name", ALL_OPERATIONS, str)
FilterByStatus = FilterBy("status", COMMON_OPERATIONS, str)


# Parsing / Conversion

type SimplifiedValue = str | int | tuple[str | int, ...]


def filters_to_query(filters: Iterable[Filter], validate: FilterValidator) -> QueryParameters:
    query = {}

    for filter_ in filters:
        # make value persistent
        if isinstance(filter_.value, Generator):
            filter_.value = tuple(filter_.value)

        validate(filter_)

        name = _attribute_name_to_camel_case(name=filter_.attr)
        simplified_value = _simplify_value(value=filter_.value)
        _check_no_operation_value_conflict(operation=filter_.op, value=simplified_value)
        operation = _get_operation_name_for_query(operation=filter_.op, value=simplified_value)
        value = _prepare_query_param_value(value=simplified_value)

        query[f"{name}__{operation}"] = value

    return query


def _attribute_name_to_camel_case(name: str) -> str:
    first, *rest = name.split("_")
    return f"{first}{''.join(map(str.capitalize, rest))}"


def _simplify_value(value: FilterValue) -> SimplifiedValue:
    if isinstance(value, (str, int)):
        return value

    if isinstance(value, InteractiveObject):
        return value.id

    simplified_collection = deque()

    for entry in value:
        if isinstance(entry, (str, int)):
            simplified_collection.append(entry)
        elif isinstance(entry, InteractiveObject):
            simplified_collection.append(entry.id)
        else:
            message = f"Failed to simplify: {entry}"
            raise TypeError(message)

    return tuple(simplified_collection)


def _check_no_operation_value_conflict(operation: str, value: SimplifiedValue) -> None:
    is_collection = isinstance(value, tuple)

    if operation in MULTI_OPERATIONS:
        if not is_collection:
            message = f"Multiple values expected for {operation}"
            raise InvalidFilterError(message)

        if not value:
            message = "Collection for filter shouldn't be empty"
            raise InvalidFilterError(message)

    else:
        if is_collection:
            message = f"Only one value is expected for {operation}"
            raise InvalidFilterError(message)


def _get_operation_name_for_query(operation: str, value: SimplifiedValue) -> str:
    is_equal_operation = operation in EQUAL_OPERATIONS
    has_string_in_value = isinstance(value, str) or (
        isinstance(value, tuple) and any(isinstance(entry, str) for entry in value)
    )

    if is_equal_operation and has_string_in_value:
        return operation.replace("eq", "exact")

    return operation


def _prepare_query_param_value(value: SimplifiedValue) -> str:
    if isinstance(value, tuple):
        return ",".join(map(str, value))

    return str(value)
