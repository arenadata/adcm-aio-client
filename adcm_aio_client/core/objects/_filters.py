from typing import Any, Generator, NotRequired, TypedDict

# todo stupid naming, change
StrCollection = list[str] | tuple[str, ...] | set[str] | Generator[str, Any, Any]


class NameFilters(TypedDict):
    name__eq: NotRequired[str]
    name__ieq: NotRequired[str]
    name__ne: NotRequired[str]
    name__ine: NotRequired[str]
    name__contains: NotRequired[str]
    name__icontains: NotRequired[str]
    name__in: NotRequired[StrCollection]
    name__iin: NotRequired[StrCollection]
    name__exclude: NotRequired[StrCollection]
    name__iexclude: NotRequired[StrCollection]


class DisplayNameFilters(TypedDict):
    display_name__eq: NotRequired[str]
    display_name__ieq: NotRequired[str]
    display_name__ne: NotRequired[str]
    display_name__ine: NotRequired[str]
    display_name__contains: NotRequired[str]
    display_name__icontains: NotRequired[str]
    display_name__in: NotRequired[StrCollection]
    display_name__iin: NotRequired[StrCollection]
    display_name__exclude: NotRequired[StrCollection]
    display_name__iexclude: NotRequired[StrCollection]


class AnyNameFilters(NameFilters, DisplayNameFilters): ...


class StatusFilters(TypedDict):
    status__eq: NotRequired[str]
    status__ne: NotRequired[str]
    status__in: NotRequired[StrCollection]
    status__exclude: NotRequired[StrCollection]


class AnyNameStatusFilters(AnyNameFilters, StatusFilters): ...
