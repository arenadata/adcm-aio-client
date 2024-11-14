from functools import cached_property
from typing import Literal, Self

from adcm_aio_client.core.objects._accessors import (
    NonPaginatedChildAccessor,
    PaginatedAccessor,
    PaginatedChildAccessor,
)
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.objects._common import Deletable
from adcm_aio_client.core.types import Endpoint


class Bundle(Deletable, InteractiveObject): ...


class Cluster(Deletable, InteractiveObject):
    # data-based properties

    @property
    def id(self: Self) -> int:
        return int(self._data["id"])

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

    async def get_status(self: Self) -> Literal["up", "down"]:
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]

    async def set_ansible_forks(self: Self, value: int) -> Self:
        # todo
        ...

    # nodes and managers to access

    @cached_property
    def services(self: Self) -> "ServicesNode":
        return ServicesNode(parent=self, path=(*self.get_own_path(), "services"), requester=self._requester)

    # todo IMPLEMENT:
    #  Nodes:
    #  - hosts: "ClusterHostsNode"
    #  - imports (probably not an accessor node, but some cool class)
    #  - actions
    #  - upgrades
    #  - config-groups
    #  Managers:
    #  - config
    #  - mapping

    def get_own_path(self: Self) -> Endpoint:
        return "clusters", self.id


class ClustersNode(PaginatedAccessor[Cluster, None]):
    class_type = Cluster

    def get_own_path(self: Self) -> Endpoint:
        return ("clusters",)


class Service(InteractiveChildObject[Cluster]):
    @property
    def id(self: Self) -> int:
        return int(self._data["id"])

    def get_own_path(self: Self) -> Endpoint:
        return (*self._parent.get_own_path(), "services", self.id)

    @cached_property
    def components(self: Self) -> "ComponentsNode":
        return ComponentsNode(parent=self, path=(*self.get_own_path(), "components"), requester=self._requester)


class ServicesNode(PaginatedChildAccessor[Cluster, Service, None]):
    class_type = Service


class Component(InteractiveChildObject[Service]):
    @property
    def id(self: Self) -> int:
        return int(self._data["id"])

    def get_own_path(self: Self) -> Endpoint:
        return (*self._parent.get_own_path(), "components", self.id)


class ComponentsNode(NonPaginatedChildAccessor[Service, Component, None]):
    class_type = Component
