from functools import cached_property
from typing import Self

from asyncstdlib.functools import cached_property as async_cached_property

from adcm_aio_client.core.errors import NotFoundError
from adcm_aio_client.core.objects._accessors import (
    PaginatedAccessor,
    PaginatedChildAccessor,
)
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
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
from adcm_aio_client.core.types import Endpoint


class Bundle(Deletable, InteractiveObject): ...


class Host(Deletable, InteractiveObject): ...


class Cluster(
    WithStatus,
    Deletable,
    WithActions,
    WithUpgrades,
    WithConfig,
    WithActionHostGroups,
    WithConfigGroups,
    InteractiveObject,
):
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
        return "clusters", self.id


class ClustersNode(PaginatedAccessor[Cluster, None]):
    class_type = Cluster

    def get_own_path(self: Self) -> Endpoint:
        return ("clusters",)


class HostsInClusterNode(PaginatedAccessor[Host, None]):
    class_type = Host


class Service(
    WithStatus,
    Deletable,
    WithActions,
    WithConfig,
    WithActionHostGroups,
    WithConfigGroups,
    InteractiveChildObject[Cluster],
):
    @property
    def id(self: Self) -> int:
        return int(self._data["id"])

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


class Component(
    WithStatus, WithActions, WithConfig, WithActionHostGroups, WithConfigGroups, InteractiveChildObject[Service]
):
    @property
    def id(self: Self) -> int:
        return int(self._data["id"])

    @property
    def name(self: Self) -> int:
        return int(self._data["name"])

    @property
    def display_name(self: Self) -> int:
        return int(self._data["displayName"])

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
        return self._parent._parent

    @cached_property
    def hosts(self: Self) -> HostsInClusterNode:
        return HostsInClusterNode(
            path=(*self.cluster.get_own_path(), "hosts"),
            requester=self._requester,
            # filter=Filter({"componentId": self.id}),  # TODO: implement
        )

    def get_own_path(self: Self) -> Endpoint:
        return *self._parent.get_own_path(), "components", self.id


class ComponentsNode(PaginatedChildAccessor[Service, Component, None]):
    class_type = Component
