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
from typing import Generator, Iterable, Self

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
type SimplifiedValue = str | int | tuple[str | int, ...]


@dataclass(slots=True)
class Filter:
    attr: str
    op: str
    value: FilterValue


@dataclass(slots=True, frozen=True)
class FilterBy:
    attr: str
    operations: set[str] | frozenset[str] | tuple[str, ...]
    single_input: type


class Filtering:
    def __init__(self: Self, *allowed: FilterBy) -> None:
        self._allowed = {entry.attr: entry for entry in allowed}

    def inline_filters_to_query(self: Self, filters: dict[str, FilterValue]) -> QueryParameters:
        converted_filters = deque()

        for inline_filter, value in filters.items():
            attr, op = inline_filter.rsplit("__", maxsplit=1)
            filter_ = Filter(attr=attr, op=op, value=value)
            converted_filters.append(filter_)

        return self.to_query(filters=converted_filters)

    def to_query(self: Self, filters: Iterable[Filter]) -> QueryParameters:
        query = {}

        for filter_ in filters:
            # make value persistent
            if isinstance(filter_.value, Generator):
                filter_.value = tuple(filter_.value)

            self._check_allowed(filter_)

            name = self._attribute_name_to_camel_case(name=filter_.attr)
            simplified_value = self._simplify_value(value=filter_.value)
            self._check_no_operation_value_conflict(operation=filter_.op, value=simplified_value)
            operation = filter_.op
            value = self._prepare_query_param_value(value=simplified_value)

            query[f"{name}__{operation}"] = value

        return query

    def _check_allowed(self: Self, filter_: Filter) -> None:
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

    def _attribute_name_to_camel_case(self: Self, name: str) -> str:
        first, *rest = name.split("_")
        return f"{first}{''.join(map(str.capitalize, rest))}"

    def _simplify_value(self: Self, value: FilterValue) -> SimplifiedValue:
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

    def _check_no_operation_value_conflict(self: Self, operation: str, value: SimplifiedValue) -> None:
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

    def _prepare_query_param_value(self: Self, value: SimplifiedValue) -> str:
        if isinstance(value, tuple):
            return ",".join(map(str, value))

        return str(value)


FilterByName = FilterBy("name", ALL_OPERATIONS, str)
FilterByDisplayName = FilterBy("display_name", ALL_OPERATIONS, str)
FilterByStatus = FilterBy("status", COMMON_OPERATIONS, str)
