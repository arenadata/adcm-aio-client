from functools import cached_property
from typing import TYPE_CHECKING, Iterable, Self, Union

from adcm_aio_client.core.errors import OperationError
from adcm_aio_client.core.objects._accessors import AccessorFilter, PaginatedAccessor, PaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject
from adcm_aio_client.core.objects._common import Deletable
from adcm_aio_client.core.types import (
    AwareOfOwnPath,
    Endpoint,
    QueryParameters,
    Requester,
    RequesterResponse,
    WithProtectedRequester,
)
from adcm_aio_client.core.utils import safe_gather

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Host


class ConfigHostGroup(InteractiveChildObject, Deletable):
    PATH_PREFIX = "config-groups"

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def description(self: Self) -> str:
        return self._data["description"]

    @cached_property
    def hosts(self: Self) -> "HostInHostGroupNode":
        return HostInHostGroupNode(path=(*self.get_own_path(), "hosts"), requester=self._requester)

    def save(self: Self) -> ...: ...

    def reset(self: Self) -> ...: ...

    def validate(self: Self) -> ...: ...


class ConfigHostGroupNode(PaginatedChildAccessor):
    class_type = ConfigHostGroup

    async def create(  # TODO: can create CHG with subset of `hosts` if adding some of them leads to an error
        self: Self, name: str, description: str = "", hosts: list["Host"] | None = None
    ) -> ConfigHostGroup:
        response = await self._requester.post(*self._path, data={"name": name, "description": description})
        chg = ConfigHostGroup(parent=self._parent, data=response.as_dict())

        if not hosts:
            return chg

        path = *chg.get_own_path(), "hosts"
        errors = await safe_gather(
            coros=(self._requester.post(*path, data={"hostId": host.id}) for host in hosts), objects=hosts
        )

        if errors:
            errors = ", ".join(str(err) for err in errors)
            raise OperationError(f"Some hosts can't be added to {chg}: {errors}")

        return chg


class Filter: ...  # TODO: implement


class HostInHostGroupNode(PaginatedAccessor):
    def __new__(cls: type[Self], path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None) -> Self:
        _ = path, requester, accessor_filter
        if not hasattr(cls, "class_type"):
            from adcm_aio_client.core.objects.cm import Host

            cls.class_type = Host

        return super().__new__(cls)

    async def add(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        errors = await safe_gather(
            coros=(self._requester.post(*self._path, data={"hostId": host.id}) for host in hosts),
            objects=hosts,
        )

        if errors:
            errors = ", ".join(str(err) for err in errors)
            raise OperationError(f"Some hosts can't be added to config host group: {errors}")

    async def remove(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        errors = await safe_gather(
            coros=(self._requester.delete(*self._path, host.id) for host in hosts), objects=hosts
        )

        if errors:
            errors = ", ".join(str(err) for err in errors)
            raise OperationError(f"Some hosts can't be removed from config host group: {errors}")

    async def set(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        await self.remove(host=await self.list())
        await self.add(host=await self._get_hosts_from_args(host=host))

    async def _get_hosts_from_args(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> Iterable["Host"]:
        if isinstance(host, Filter):
            return await self.filter(host)  # type: ignore  # TODO
        return host if isinstance(host, Iterable) else [host]

    async def _request_endpoint(self: Self, query: QueryParameters) -> RequesterResponse:
        """CHG/hosts response have too little information to construct Host"""

        response = (await super()._request_endpoint(query)).as_list()
        ids = ",".join(str(host["id"]) for host in response)

        return await self._requester.get("hosts", query={"id__in": ids})


class WithConfigHostGroups(WithProtectedRequester, AwareOfOwnPath):
    @cached_property
    def config_host_groups(self: Self) -> ConfigHostGroupNode:
        return ConfigHostGroupNode(parent=self, path=(*self.get_own_path(), "config-groups"), requester=self._requester)
