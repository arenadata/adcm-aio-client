from typing import TYPE_CHECKING, Iterable, Self, Union

from adcm_aio_client.core.objects._accessors import AccessorFilter, PaginatedAccessor, PaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject
from adcm_aio_client.core.types import Endpoint, QueryParameters, Requester, RequesterResponse
from adcm_aio_client.core.utils import safe_gather

if TYPE_CHECKING:
    from adcm_aio_client.core.host_groups.action_group import ActionHostGroup
    from adcm_aio_client.core.host_groups.config_group import ConfigHostGroup
    from adcm_aio_client.core.objects.cm import Cluster, Component, Host, HostProvider, Service


class Filter: ...  # TODO: implement


class HostInHostGroupNode(PaginatedAccessor["Host", None]):
    group_type: str

    def __new__(cls: type[Self], path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None) -> Self:
        _ = path, requester, accessor_filter
        if not hasattr(cls, "class_type"):
            from adcm_aio_client.core.objects.cm import Host

            cls.class_type = Host

        return super().__new__(cls)

    async def add(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        error = await safe_gather(
            coros=(self._requester.post(*self._path, data={"hostId": host.id}) for host in hosts),
            msg=f"Some hosts can't be added to {self.group_type} host group",
        )
        if error is not None:
            raise error

    async def remove(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        error = await safe_gather(
            coros=(self._requester.delete(*self._path, host.id) for host in hosts),
            msg=f"Some hosts can't be removed from {self.group_type} host group",
        )

        if error is not None:
            raise error

    async def set(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        in_group_ids = {host["id"] for host in (await super()._request_endpoint(query={})).as_list()}

        to_remove_ids = {host_id for host_id in in_group_ids if host_id not in (host.id for host in hosts)}
        to_add_ids = {host.id for host in hosts if host.id not in in_group_ids}

        if to_remove_ids:
            await self.remove(host=Filter(id__in=to_remove_ids))  # type: ignore  # TODO: implement
        if to_add_ids:
            await self.add(host=Filter(id__in=to_add_ids))  # type: ignore  # TODO: implement

    async def _get_hosts_from_args(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> list["Host"]:
        if isinstance(host, Filter):
            return await self.filter(host)  # type: ignore  # TODO

        return list(host) if isinstance(host, Iterable) else [host]

    async def _request_endpoint(self: Self, query: QueryParameters) -> RequesterResponse:
        """HostGroup/hosts response have too little information to construct Host"""

        data = (await super()._request_endpoint(query)).as_list()
        ids = ",".join(str(host["id"]) for host in data)
        query = {"id__in": ids} if ids else {"id__in": "-1"}  # non-existent id to fetch 0 hosts

        return await self._requester.get("hosts", query=query)


class HostGroupNode[
    Parent: Cluster | Service | Component | HostProvider,
    Child: ConfigHostGroup | ActionHostGroup,
](PaginatedChildAccessor[Parent, Child, None]):
    async def create(  # TODO: can create HG with subset of `hosts` if adding some of them leads to an error
        self: Self, name: str, description: str = "", hosts: list["Host"] | None = None
    ) -> InteractiveChildObject:
        response = await self._requester.post(*self._path, data={"name": name, "description": description})
        host_group = self.class_type(parent=self._parent, data=response.as_dict())

        if not hosts:
            return host_group

        path = *host_group.get_own_path(), "hosts"
        error = await safe_gather(
            coros=(self._requester.post(*path, data={"hostId": host.id}) for host in hosts),
            msg=f"Some hosts can't be added to {host_group}",
        )
        if error is not None:
            raise error

        return host_group
