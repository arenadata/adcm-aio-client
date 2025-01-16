from collections.abc import AsyncGenerator, Iterable
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING, Any, Self, Union
import asyncio
import builtins

from adcm_aio_client import Filter
from adcm_aio_client._filters import FilterValue
from adcm_aio_client._types import Endpoint, HostID, QueryParameters, Requester, RequesterResponse
from adcm_aio_client._utils import safe_gather
from adcm_aio_client.objects._accessors import (
    DefaultQueryParams as AccessorFilter,
)
from adcm_aio_client.objects._accessors import (
    NonPaginatedAccessor,
    PaginatedChildAccessor,
    filters_to_inline,
)

if TYPE_CHECKING:
    from adcm_aio_client.host_groups._action_group import ActionHostGroup
    from adcm_aio_client.host_groups._config_group import ConfigHostGroup
    from adcm_aio_client.objects import Cluster, Component, Host, HostProvider, Service


class HostsInHostGroupNode(NonPaginatedAccessor["Host"]):
    group_type: str

    def __new__(cls: type[Self], path: Endpoint, requester: Requester, accessor_filter: AccessorFilter = None) -> Self:
        _ = path, requester, accessor_filter
        if not hasattr(cls, "class_type"):
            from adcm_aio_client.objects import Host
            from adcm_aio_client.objects._cm import HostsAccessor

            cls.class_type = Host
            cls.filtering = HostsAccessor.filtering

        return super().__new__(cls)

    async def add(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        host_ids = await self._retrieve_host_ids(host=host, sources=(self._candidates_ep,))
        await self._add_hosts_to_group(host_ids)

    async def remove(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        host_ids = await self._retrieve_host_ids(host=host, sources=(self._path,))
        await self._remove_hosts_from_group(host_ids)

    async def set(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts_to_set = await self._retrieve_host_ids(host=host, sources=(self._candidates_ep, self._path))

        response = await super()._request_endpoint(query={})
        hosts_in_group: set[HostID] = {host["id"] for host in response.as_list()}

        to_remove_ids = hosts_in_group - hosts_to_set
        to_add_ids = hosts_to_set - hosts_in_group

        if to_remove_ids:
            await self._remove_hosts_from_group(ids=to_remove_ids)

        if to_add_ids:
            await self._add_hosts_to_group(ids=to_add_ids)

    async def iter(self: Self, **filters: FilterValue) -> AsyncGenerator["Host", Any]:
        response = await self._request_endpoint(query={}, filters=filters)
        results = response.as_dict()["results"]
        for record in results:
            yield self._create_object(record)

    @property
    def _candidates_ep(self: Self) -> Endpoint:
        parent_path = self._path[:-1]
        return *parent_path, "host-candidates"

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

    async def _retrieve_host_ids(
        self: Self, host: Union["Host", Iterable["Host"], Filter], sources: Iterable[Endpoint]
    ) -> builtins.set[HostID]:
        from adcm_aio_client.objects import Host

        if isinstance(host, Host):
            return {host.id}

        if isinstance(host, Iterable):
            return {h.id for h in host}

        inline_filters = filters_to_inline(host)
        query = self.filtering.inline_filters_to_query(inline_filters)
        get_filtered_hosts = partial(self._requester.get, query=query)
        responses = await asyncio.gather(*(get_filtered_hosts(*source) for source in sources))
        data_from_responses = chain(*(response.as_list() for response in responses))
        return {entry["id"] for entry in data_from_responses}

    async def _request_endpoint(
        self: Self, query: QueryParameters, filters: dict[str, Any] | None = None
    ) -> RequesterResponse:
        """HostGroup/hosts response have too little information to construct Host"""

        response = await super()._request_endpoint(query, filters)
        hosts_in_group: tuple[HostID, ...] = tuple(host["id"] for host in response.as_list())

        if hosts_in_group:
            query = {"limit": len(hosts_in_group), "id__in": ",".join(map(str, hosts_in_group))}
        else:
            # if there's no entries, pass non-existing id for empty full-blown response
            query = {"id__in": "-1"}

        return await self._requester.get("hosts", query=query)

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
