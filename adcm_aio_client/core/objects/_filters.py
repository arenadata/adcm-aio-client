from typing import Any, Generator, Literal, NotRequired, TypedDict
from adcm_aio_client.core.filters import Filter

# todo stupid naming, change
StrCollection = list[str] | tuple[str, ...] | set[str] | Generator[str, Any, Any]

type SingleStrOperation = Literal["eq", "ieq", "ne", "ine", "contains", "icontains"]
type MultipleStrOperation = Literal["in", "iin", "exclude", "iexclude"]

type FilterByName = (
    Filter[Literal["name"], SingleStrOperation, str] | Filter[Literal["name"], MultipleStrOperation, StrCollection]
)

type FilterByDisplayName = (
    Filter[Literal["display_name"], SingleStrOperation, str]
    | Filter[Literal["display_name"], MultipleStrOperation, StrCollection]
)

type FilterByStatus = (
    Filter[Literal["status"], Literal["eq", "ne"], str]
    | Filter[Literal["status"], Literal["in", "exclude"], StrCollection]
)

type FilterByAnyName = FilterByName | FilterByDisplayName
type FilterByAnyNameAndStatus = FilterByAnyName | FilterByStatus
