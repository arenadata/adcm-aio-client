from functools import cached_property
from typing import Self

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
from adcm_aio_client.core.types import ADCMEntityStatus, Endpoint


class Bundle(Deletable, InteractiveObject): ...


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
    @cached_property
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

    def get_own_path(self: Self) -> Endpoint:
        return ("clusters",)


class Service(
    WithStatus,
    Deletable,
    WithActions,
    WithConfig,
    WithActionHostGroups,
    WithConfigGroups,
    InteractiveChildObject[Cluster],
):
    # PATH_PREFIX = "services"

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
        return *self._parent.get_own_path(), "services", self.id

    @cached_property
    def components(self: Self) -> "ComponentsNode":
        return ComponentsNode(parent=self, path=(*self.get_own_path(), "components"), requester=self._requester)


class ServicesNode(PaginatedChildAccessor[Cluster, Service, None]):
    class_type = Service


class Component(InteractiveChildObject[Service]):
    def get_own_path(self: Self) -> Endpoint:
        return (*self._parent.get_own_path(), "components", self.id)


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

    @cached_property
    async def cluster(self: Self) -> Cluster | None:
        if not self._data["cluster"]:
            return None
        return await Cluster.with_id(requester=self._requester, object_id=self._data["cluster"]["id"])

    @cached_property
    async def hostprovider(self: Self) -> HostProvider:
        return await HostProvider.with_id(requester=self._requester, object_id=self._data["hostprovider"]["id"])

    def get_own_path(self: Self) -> Endpoint:
        return self.PATH_PREFIX, self.id


class HostsNode(PaginatedAccessor[Host, None]):
    class_type = Host


class HostsInClusterNode(PaginatedAccessor[Host, None]):
    class_type = Host
