from collections.abc import AsyncGenerator, Iterable
from functools import partial
from typing import TYPE_CHECKING, Any, Self, Union

from adcm_aio_client.core.filters import Filter, FilterValue
from adcm_aio_client.core.objects._accessors import (
    DefaultQueryParams as AccessorFilter,
)
from adcm_aio_client.core.objects._accessors import (
    NonPaginatedAccessor,
    PaginatedChildAccessor,
    filters_to_inline,
)
from adcm_aio_client.core.types import Endpoint, HostID, QueryParameters, Requester, RequesterResponse
from adcm_aio_client.core.utils import safe_gather

if TYPE_CHECKING:
    from adcm_aio_client.core.host_groups.action_group import ActionHostGroup
    from adcm_aio_client.core.host_groups.config_group import ConfigHostGroup
    from adcm_aio_client.core.objects.cm import Cluster, Component, Host, HostProvider, Service


class HostsInHostGroupNode(NonPaginatedAccessor["Host"]):
    group_type: str

    def __new__(cls: type[Self], path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None) -> Self:
        _ = path, requester, accessor_filter
        if not hasattr(cls, "class_type"):
            from adcm_aio_client.core.objects.cm import Host, HostsAccessor

            cls.class_type = Host
            cls.filtering = HostsAccessor.filtering

        return super().__new__(cls)

    async def add(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        await self._add_hosts_to_group(h.id for h in hosts)

    async def remove(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        await self._remove_hosts_from_group(h.id for h in hosts)

    async def set(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        in_group_ids = {host["id"] for host in (await super()._request_endpoint(query={})).as_list()}

        to_remove_ids = {host_id for host_id in in_group_ids if host_id not in (host.id for host in hosts)}
        to_add_ids = {host.id for host in hosts if host.id not in in_group_ids}

        if to_remove_ids:
            await self._remove_hosts_from_group(ids=to_remove_ids)
        if to_add_ids:
            await self._add_hosts_to_group(ids=to_add_ids)

    async def _add_hosts_to_group(self: Self, ids: Iterable[HostID]) -> None:
        add_by_id = partial(self._requester.post, *self._path)
        add_coros = (add_by_id(data={"hostId": id_}) for id_ in ids)
        error = await safe_gather(
            coros=add_coros,
            msg=f"Some hosts can't be added to {self.group_type} host group",
        )
        if error is not None:
            raise error

    async def _remove_hosts_from_group(self: Self, ids: Iterable[HostID]) -> None:
        delete_by_id = partial(self._requester.delete, *self._path)
        delete_coros = map(delete_by_id, ids)
        error = await safe_gather(
            coros=delete_coros,
            msg=f"Some hosts can't be removed from {self.group_type} host group",
        )

        if error is not None:
            raise error

    async def _get_hosts_from_args(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> list["Host"]:
        if isinstance(host, Filter):
            inline_filters = filters_to_inline(host)
            return await self.filter(**inline_filters)

        return list(host) if isinstance(host, Iterable) else [host]

    async def _request_endpoint(
        self: Self, query: QueryParameters, filters: dict[str, Any] | None = None
    ) -> RequesterResponse:
        """HostGroup/hosts response have too little information to construct Host"""

        data = (await super()._request_endpoint(query, filters)).as_list()
        ids = {host["id"] for host in data}
        limit = len(ids)
        ids = ",".join(str(id_) for id_ in ids)
        query = {"id__in": ids, "limit": limit} if ids else {"id__in": "-1"}  # non-existent id to fetch 0 hosts

        return await self._requester.get("hosts", query=query)

    async def iter(self: Self, **filters: FilterValue) -> AsyncGenerator["Host", Any]:
        response = await self._request_endpoint(query={}, filters=filters)
        results = response.as_dict()["results"]
        for record in results:
            yield self._create_object(record)

    def _extract_results_from_response(self: Self, response: RequesterResponse) -> list[dict]:
        return response.as_dict()["results"]


class HostGroupNode[
    Parent: Cluster | Service | Component | HostProvider,
    Child: ConfigHostGroup | ActionHostGroup,
](PaginatedChildAccessor[Parent, Child]):
    async def create(  # TODO: can create HG with subset of `hosts` if adding some of them leads to an error
        self: Self, name: str, description: str = "", hosts: list["Host"] | None = None
    ) -> Child:
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
