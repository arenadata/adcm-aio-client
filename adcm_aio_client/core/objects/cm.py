from functools import cached_property
from typing import Literal, Self

from adcm_aio_client.core.objects._accessors import PaginatedAccessor, PaginatedChildAccessor
from adcm_aio_client.core.objects._base import InteractiveChildObject, InteractiveObject
from adcm_aio_client.core.objects._common import Deletable
from adcm_aio_client.core.types import Endpoint


class Bundle(Deletable, InteractiveObject): ...


class Cluster(Deletable, InteractiveObject):
    # data-based properties

    @cached_property
    def id(self: Self) -> int:
        return int(self._data["id"])

    @cached_property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @cached_property
    def description(self: Self) -> str:
        return str(self._data["description"])

    # related/dynamic data access

    @property
    async def status(self: Self) -> Literal["up", "down"]:
        response = await self._requester.get(*self.get_own_path())
        return response.as_dict()["status"]

    @property
    async def bundle(self: Self) -> Bundle:
        prototype_id = self._data["prototype"]["id"]
        response = await self._requester.get("prototypes", prototype_id)

        bundle_id = response.as_dict()["bundle"]["id"]
        response = await self._requester.get("bundles", bundle_id)

        return self._construct(what=Bundle, from_data=response.as_dict())

    # object-specific methods

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
    def get_own_path(self: Self) -> Endpoint:
        return ("clusters",)


class Service(InteractiveChildObject[Cluster]): ...


class ServicesNode(PaginatedChildAccessor[Cluster, Service, None]): ...
