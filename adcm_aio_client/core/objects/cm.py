from functools import cached_property
from typing import Iterable, Literal, Self
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client.core.errors import NotFoundError, OperationError, ResponseError
from adcm_aio_client.core.objects._accessors import (
    PaginatedAccessor,
    PaginatedChildAccessor,
)
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject, RootInteractiveObject
from adcm_aio_client.core.objects._common import (
    Deletable,
    WithActionHostGroups,
    WithActions,
    WithConfig,
    WithConfigGroups,
    WithStatus,
    WithUpgrades,
)
from adcm_aio_client.core.objects._imports import ClusterImports
from adcm_aio_client.core.objects._mapping import ClusterMapping
from adcm_aio_client.core.types import ADCMEntityStatus, Endpoint, Requester, WithProtectedRequester

type Filter = object  # TODO: implement


class ADCM(InteractiveObject, WithActions, WithConfig):
    @cached_property
    def id(self: Self) -> int:
        return 1

    @async_cached_property
    async def version(self: Self) -> str:
        # TODO: override root_path for being without /api/v2
        response = await self._requester.get("versions")
        return response.as_dict()["adcm"]["version"]

    def get_own_path(self: Self) -> Endpoint:
        return ("adcm",)


class License(WithProtectedRequester):
    def __init__(self: Self, requester: Requester, prototypes_data: dict) -> None:
        self._license_prototype_id = prototypes_data["id"]
        self._data = prototypes_data["license"]
        self._requester = requester

    @property
    def text(self: Self) -> str:
        return str(self._data["text"])

    @property
    def state(self: Self) -> Literal["absent", "accepted", "unaccepted"]:
        return self._data["status"]

    async def accept(self: Self) -> str:
        await self._requester.post(
            "prototypes", self._license_prototype_id, "license", "accept", data={}
        )
        self._data["status"] = "accepted"
        return self._data["status"]


class Bundle(Deletable, RootInteractiveObject):
    PATH_PREFIX = "bundles"

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def display_name(self: Self) -> str:
        return str(self._data["display_name"])

    @property
    def version(self: Self) -> str:
        return str(self._data["version"])

    @property
    def edition(self: Self) -> Literal["community", "enterprise"]:
        return self._data["edition"]

    @property
    def signature_status(self: Self) -> Literal["invalid", "valid", "absent"]:
        return self._data["signatureStatus"]

    @property
    def _type(self: Self) -> Literal["cluster", "provider"]:
        return self._data["mainPrototype"]["type"]

    def license(self: Self) -> License:
        return License(self._requester, self._data["mainPrototype"])

    def get_own_path(self: Self) -> Endpoint:
        return self.PATH_PREFIX, self.id


class BundlesNode(PaginatedAccessor[Bundle, None]):
    class_type = Bundle

    def get_own_path(self: Self) -> Endpoint:
        return ("bundles",)


class Cluster(
    WithStatus,
    Deletable,
    WithActions,
    WithUpgrades,
    WithConfig,
    WithActionHostGroups,
    WithConfigGroups,
    RootInteractiveObject,
):
    PATH_PREFIX = "clusters"
    # data-based properties

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        return str(self._data["description"])

    # related/dynamic data access

    # todo think how such properties will be invalidated when data is updated
    #  during `refresh()` / `reread()` calls.
    #  See cache invalidation or alternatives in documentation for `cached_property`
    @async_cached_property
    async def bundle(self: Self) -> Bundle:
        prototype_id = self._data["prototype"]["id"]
        response = await self._requester.get("prototypes", prototype_id)

        bundle_id = response.as_dict()["bundle"]["id"]
        response = await self._requester.get("bundles", bundle_id)

        return self._construct(what=Bundle, from_data=response.as_dict())

    # object-specific methods
    async def set_ansible_forks(self: Self, value: int) -> Self:
        await self._requester.post(
            *self.get_own_path(), "ansible-config", data={"config": {"defaults": {"forks": value}}, "adcmMeta": {}}
        )
        return self

    # nodes and managers to access

    @cached_property
    def mapping(self: Self) -> ClusterMapping:
        return ClusterMapping()

    @cached_property
    def services(self: Self) -> "ServicesNode":
        return ServicesNode(parent=self, path=(*self.get_own_path(), "services"), requester=self._requester)

    @cached_property
    def hosts(self: Self) -> "HostsInClusterNode":
        return HostsInClusterNode(path=(*self.get_own_path(), "hosts"), requester=self._requester)

    @cached_property
    def imports(self: Self) -> ClusterImports:
        return ClusterImports()

    def get_own_path(self: Self) -> Endpoint:
        return self.PATH_PREFIX, self.id


class ClustersNode(PaginatedAccessor[Cluster, None]):
    class_type = Cluster


class Service(
    WithStatus,
    Deletable,
    WithActions,
    WithConfig,
    WithActionHostGroups,
    WithConfigGroups,
    InteractiveChildObject[Cluster],
):
    PATH_PREFIX = "services"

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @cached_property
    def cluster(self: Self) -> Cluster:
        return self._parent

    def get_own_path(self: Self) -> Endpoint:
        return *self._parent.get_own_path(), self.PATH_PREFIX, self.id

    @cached_property
    def components(self: Self) -> "ComponentsNode":
        return ComponentsNode(parent=self, path=(*self.get_own_path(), "components"), requester=self._requester)


class ServicesNode(PaginatedChildAccessor[Cluster, Service, None]):
    class_type = Service


class Component(
    WithStatus, WithActions, WithConfig, WithActionHostGroups, WithConfigGroups, InteractiveChildObject[Service]
):
    PATH_PREFIX = "components"

    @property
    def name(self: Self) -> str:
        return self._data["name"]

    @property
    def display_name(self: Self) -> str:
        return self._data["displayName"]

    @async_cached_property
    async def constraint(self: Self) -> list[int | str]:
        response = (await self._requester.get(*self.cluster.get_own_path(), "mapping", "components")).as_list()
        for component in response:
            if component["id"] == self.id:
                return component["constraints"]

        raise NotFoundError

    @cached_property
    def service(self: Self) -> Service:
        return self._parent

    @cached_property
    def cluster(self: Self) -> Cluster:
        return self.service.cluster

    @cached_property
    def hosts(self: Self) -> "HostsAccessor":
        return HostsAccessor(
            path=(*self.cluster.get_own_path(), "hosts"),
            requester=self._requester,
            accessor_filter={"componentId": self.id},
        )

    def get_own_path(self: Self) -> Endpoint:
        return *self._parent.get_own_path(), self.PATH_PREFIX, self.id


class ComponentsNode(PaginatedChildAccessor[Service, Component, None]):
    class_type = Component


class HostProvider(Deletable, WithActions, WithUpgrades, WithConfig, RootInteractiveObject):
    PATH_PREFIX = "hostproviders"
    # data-based properties

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        return str(self._data["description"])

    @property
    def display_name(self: Self) -> str:
        return str(self._data["prototype"]["displayName"])

    @cached_property
    def hosts(self: Self) -> "HostsAccessor":
        return HostsAccessor(
            path=("hosts",), requester=self._requester, accessor_filter={"hostproviderName": self.name}
        )

    def get_own_path(self: Self) -> Endpoint:
        return self.PATH_PREFIX, self.id


class HostProvidersNode(PaginatedAccessor[HostProvider, None]):
    class_type = HostProvider


class Host(Deletable, RootInteractiveObject):
    PATH_PREFIX = "hosts"

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        return str(self._data["description"])

    async def get_status(self: Self) -> ADCMEntityStatus:
        response = await self._requester.get(*self.get_own_path())
        return ADCMEntityStatus(response.as_dict()["status"])

    @async_cached_property
    async def cluster(self: Self) -> Cluster | None:
        if not self._data["cluster"]:
            return None
        return await Cluster.with_id(requester=self._requester, object_id=self._data["cluster"]["id"])

    @async_cached_property
    async def hostprovider(self: Self) -> HostProvider:
        return await HostProvider.with_id(requester=self._requester, object_id=self._data["hostprovider"]["id"])

    def get_own_path(self: Self) -> Endpoint:
        return self.PATH_PREFIX, self.id

    def __str__(self: Self) -> str:
        return f"<{self.__class__.__name__} #{self.id} {self.name}>"


class HostsAccessor(PaginatedAccessor[Host, dict | None]):
    class_type = Host


class HostsInClusterNode(HostsAccessor):
    async def add(self: Self, host: Host | Iterable[Host] | None = None, filters: Filter | None = None) -> None:
        hosts = await self._get_hosts_from_arg_or_filter(host=host, filters=filters)

        await self._requester.post(*self._path, data=[{"hostId": host.id} for host in hosts])

    async def remove(self: Self, host: Host | Iterable[Host] | None = None, filters: Filter | None = None) -> None:
        hosts = await self._get_hosts_from_arg_or_filter(host=host, filters=filters)

        results = await asyncio.gather(
            *(self._requester.delete(*self._path, host_.id) for host_ in hosts), return_exceptions=True
        )

        errors = set()
        for host_, result in zip(hosts, results):
            if isinstance(result, ResponseError):
                errors.add(str(host_))

        if errors:
            errors = ", ".join(errors)
            raise OperationError(f"Some hosts can't be deleted from cluster: {errors}")

    async def _get_hosts_from_arg_or_filter(
        self: Self, host: Host | Iterable[Host] | None = None, filters: Filter | None = None
    ) -> Iterable[Host]:
        if all((host, filters)):
            raise ValueError("`host` and `filters` arguments are mutually exclusive.")

        if host:
            hosts = [host] if isinstance(host, Host) else host
        else:
            hosts = await self.filter(filters)  # type: ignore  # TODO

        return hosts
