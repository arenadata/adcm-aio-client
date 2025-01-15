from collections import deque
from contextlib import suppress
from functools import cached_property
from typing import Any, Self

from asyncstdlib.functools import CachedProperty

from adcm_aio_client.core.types import (
    AwareOfOwnPath,
    Endpoint,
    MaintenanceModeStatus,
    Requester,
    WithProtectedRequester,
    WithRequesterProperty,
)


class InteractiveObject(WithProtectedRequester, WithRequesterProperty, AwareOfOwnPath):
    PATH_PREFIX: str
    _delete_on_refresh: deque[str]

    def __init_subclass__(cls: type[Self]) -> None:
        super().__init_subclass__()

        # names of cached properties, so they can be deleted
        cls._delete_on_refresh = deque()
        for name in dir(cls):
            # None is for declared, but unset values
            attr = getattr(cls, name, None)
            if isinstance(attr, cached_property | CachedProperty):
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
        self._data = await self._retrieve_data()
        self._clear_cache()

        return self

    async def _retrieve_data(self: Self) -> dict:
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()

    def _construct[Object: "InteractiveObject"](self: Self, what: type[Object], from_data: dict[str, Any]) -> Object:
        return what(requester=self._requester, data=from_data)

    def _construct_child[Child: "InteractiveChildObject"](
        self: Self, what: type[Child], from_data: dict[str, Any]
    ) -> Child:
        return what(data=from_data, parent=self)

    def _clear_cache(self: Self) -> None:
        for name in self._delete_on_refresh:
            # Works for cached_property. Suppresses errors on deleting values not yet cached (absent in self.__dict__)
            with suppress(AttributeError):
                delattr(self, name)

    def __str__(self: Self) -> str:
        return self._repr

    def __repr__(self: Self) -> str:
        return self._repr

    @property
    def _repr(self: Self) -> str:
        name = getattr(self, "name", None)
        name = f" {name}" if isinstance(name, str) else ""
        return f"<{self.__class__.__name__} #{self.id}{name}>"


class RootInteractiveObject(InteractiveObject):
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


class InteractiveChildObject[Parent: InteractiveObject](InteractiveObject):
    def __init__(self: Self, parent: Parent, data: dict[str, Any]) -> None:
        super().__init__(requester=parent.requester, data=data)
        self._parent = parent

    def get_own_path(self: Self) -> Endpoint:
        return *self._parent.get_own_path(), self.PATH_PREFIX, self.id

    @classmethod
    async def with_id(cls: type[Self], parent: Parent, object_id: int) -> Self:
        object_path = (*parent.get_own_path(), cls.PATH_PREFIX, str(object_id))
        response = await parent.requester.get(*object_path)
        return cls(parent=parent, data=response.as_dict())


class MaintenanceMode:
    def __init__(
        self: Self, maintenance_mode_status: MaintenanceModeStatus, requester: Requester, path: Endpoint
    ) -> None:
        self._maintenance_mode_status = maintenance_mode_status
        self._requester = requester
        self._path = path

    def __repr__(self: Self) -> str:
        return self._maintenance_mode_status

    def __str__(self: Self) -> str:
        return self._maintenance_mode_status

    @property
    def value(self: Self) -> str:
        return self._maintenance_mode_status

    async def on(self: Self) -> None:
        current_mm_status = await self._requester.post(
            *self._path, "maintenance-mode", data={"maintenanceMode": MaintenanceModeStatus.ON}
        )
        self._maintenance_mode_status = current_mm_status.as_dict()["maintenanceMode"]

    async def off(self: Self) -> None:
        current_mm_status = await self._requester.post(
            *self._path, "maintenance-mode", data={"maintenanceMode": MaintenanceModeStatus.OFF}
        )
        self._maintenance_mode_status = current_mm_status.as_dict()["maintenanceMode"]
