from functools import cached_property
from typing import Any, Self

from asyncstdlib import cached_property as async_cached_property

from adcm_aio_client.core.objects._accessors import NonPaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.types import Requester


class Action(InteractiveChildObject):
    PATH_PREFIX = "actions"

    def __init__(self: Self, parent: InteractiveObject, requester: Requester, data: dict[str, Any]) -> None:
        super().__init__(parent, requester, data)
        self._verbose = False

    @cached_property
    def name(self: Self) -> str:
        return self._data["name"]

    @cached_property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    async def run(self: Self) -> dict:  # TODO: implement Task, return Task
        return (await self._requester.post(*self.get_own_path(), "run", data={"isVerbose": self._verbose})).as_dict()

    @async_cached_property
    async def _mapping_rule(self: Self) -> list[dict]:
        return (await self._rich_data)["hostComponentMapRules"]

    @async_cached_property
    async def mapping(self: Self) -> "ActionMapping":
        return ActionMapping()

    def set_verbose(self: Self) -> Self:
        self._verbose = True
        return self

    def validate(self: Self) -> None: ...  # TODO: implement

    @async_cached_property  # TODO: Config class
    async def config(self: Self) -> ...:
        return (await self._rich_data)["configuration"]

    @async_cached_property
    async def _rich_data(self: Self) -> dict:
        return (await self._requester.get(*self.get_own_path())).as_dict()


class ActionsAccessor(NonPaginatedChildAccessor):
    class_type = Action


class ActionMapping:
    def add(self: Self) -> ...: ...

    def remove(self: Self) -> ...: ...
