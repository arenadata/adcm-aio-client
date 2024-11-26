from collections import deque
from contextlib import suppress
from functools import cached_property
from typing import Any, Self

from adcm_aio_client.core.requesters import Requester
from adcm_aio_client.core.types import AwareOfOwnPath, Endpoint, WithProtectedRequester, WithRequesterProperty


class InteractiveObject(WithProtectedRequester, WithRequesterProperty, AwareOfOwnPath):
    _delete_on_refresh: deque[str]

    def __init_subclass__(cls: type[Self]) -> None:
        super().__init_subclass__()

        # names of cached properties, so they can be deleted
        cls._delete_on_refresh = deque()
        for name in dir(cls):
            # None is for declared, but unset values
            attr = getattr(cls, name, None)
            if isinstance(attr, cached_property):  # TODO: asyncstdlib.functools.CachedProperty
                cls._delete_on_refresh.append(name)

    def __init__(self: Self, requester: Requester, data: dict[str, Any]) -> None:
        self._requester = requester
        self._data = data

    @property
    def requester(self: Self) -> Requester:
        return self._requester

    @cached_property
    def id(self: Self) -> int:
        # it's the default behavior, without id many things can't be done
        return int(self._data["id"])

    async def refresh(self: Self) -> Self:
        response = await self._requester.get(*self.get_own_path())
        self._data = response.as_dict()
        self._clear_cache()

        return self

    def _construct[Object: "InteractiveObject"](self: Self, what: type[Object], from_data: dict[str, Any]) -> Object:
        return what(requester=self._requester, data=from_data)

    def _construct_child[Child: "InteractiveChildObject"](
        self: Self, what: type[Child], from_data: dict[str, Any]
    ) -> Child:
        return what(requester=self._requester, data=from_data, parent=self)

    def _clear_cache(self: Self) -> None:
        for name in self._delete_on_refresh:
            # Works for cached_property. Suppresses errors on deleting values not yet cached (absent in self.__dict__)
            with suppress(AttributeError):
                delattr(self, name)


class RootInteractiveObject(InteractiveObject):
    PATH_PREFIX: str

    def get_own_path(self: Self) -> Endpoint:
        # change here
        return self._build_own_path(self.id)

    @classmethod
    async def with_id(cls: type[Self], requester: Requester, object_id: int) -> Self:
        object_path = cls._build_own_path(object_id)
        response = await requester.get(*object_path)
        return cls(requester=requester, data=response.as_dict())

    @classmethod
    def _build_own_path(cls: type[Self], object_id: int) -> Endpoint:
        return cls.PATH_PREFIX, object_id


class InteractiveChildObject[Parent](InteractiveObject):
    def __init__(self: Self, parent: Parent, requester: Requester, data: dict[str, Any]) -> None:
        super().__init__(requester=requester, data=data)
        self._parent = parent
