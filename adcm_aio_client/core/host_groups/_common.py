from typing import TYPE_CHECKING, Iterable, Self, Union

from adcm_aio_client.core.errors import OperationError
from adcm_aio_client.core.objects._accessors import AccessorFilter, PaginatedAccessor, PaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject
from adcm_aio_client.core.types import Endpoint, QueryParameters, Requester, RequesterResponse
from adcm_aio_client.core.utils import safe_gather

if TYPE_CHECKING:
    from adcm_aio_client.core.objects.cm import Host


class Filter: ...  # TODO: implement


class HostInHostGroupNode(
    PaginatedAccessor,
):
    group_type: str

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
            raise OperationError(f"Some hosts can't be added to {self.group_type} host group: {errors}")

    async def remove(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        hosts = await self._get_hosts_from_args(host=host)
        errors = await safe_gather(
            coros=(self._requester.delete(*self._path, host.id) for host in hosts), objects=hosts
        )

        if errors:
            errors = ", ".join(str(err) for err in errors)
            raise OperationError(f"Some hosts can't be removed from {self.group_type} host group: {errors}")

    async def set(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> None:
        await self.remove(host=await self.all())
        await self.add(host=await self._get_hosts_from_args(host=host))

    async def _get_hosts_from_args(self: Self, host: Union["Host", Iterable["Host"], Filter]) -> Iterable["Host"]:
        if isinstance(host, Filter):
            return await self.filter(host)  # type: ignore  # TODO

        return host if isinstance(host, Iterable) else [host]

    async def _request_endpoint(self: Self, query: QueryParameters) -> RequesterResponse:
        """HostGroup/hosts response have too little information to construct Host"""

        response = (await super()._request_endpoint(query)).as_list()
        ids = ",".join(str(host["id"]) for host in response)
        query = {"id__in": ids} if ids else {"id__in": "-1"}  # non-existent id to fetch 0 hosts

        return await self._requester.get("hosts", query=query)


class HostGroupNode(PaginatedChildAccessor):
    class_type: InteractiveChildObject  # pyright: ignore[reportIncompatibleVariableOverride]

    async def create(  # TODO: can create HG with subset of `hosts` if adding some of them leads to an error
        self: Self, name: str, description: str = "", hosts: list["Host"] | None = None
    ) -> InteractiveChildObject:
        response = await self._requester.post(*self._path, data={"name": name, "description": description})
        host_group = self.class_type(parent=self._parent, data=response.as_dict())  # pyright: ignore[reportCallIssue]

        if not hosts:
            return host_group

        path = *host_group.get_own_path(), "hosts"
        errors = await safe_gather(
            coros=(self._requester.post(*path, data={"hostId": host.id}) for host in hosts), objects=hosts
        )

        if errors:
            errors = ", ".join(str(err) for err in errors)
            raise OperationError(f"Some hosts can't be added to {host_group}: {errors}")

        return host_group
