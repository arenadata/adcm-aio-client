from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Literal, Self
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client.core.actions._objects import Action
from adcm_aio_client.core.errors import NotFoundError
from adcm_aio_client.core.host_groups import WithActionHostGroups, WithConfigHostGroups
from adcm_aio_client.core.mapping import ClusterMapping
from adcm_aio_client.core.objects._accessors import (
    PaginatedAccessor,
    PaginatedChildAccessor,
)
from adcm_aio_client.core.objects._base import (
    InteractiveChildObject,
    InteractiveObject,
    RootInteractiveObject,
)
from adcm_aio_client.core.objects._common import (
    Deletable,
    WithActions,
    WithConfig,
    WithJobStatus,
    WithMaintenanceMode,
    WithStatus,
    WithUpgrades,
)
from adcm_aio_client.core.objects._imports import ClusterImports
from adcm_aio_client.core.requesters import BundleRetrieverInterface
from adcm_aio_client.core.types import Endpoint, JobStatus, Requester, UrlPath, WithProtectedRequester
from adcm_aio_client.core.utils import safe_gather

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
        await self._requester.post("prototypes", self._license_prototype_id, "license", "accept", data={})
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

    @property
    def license(self: Self) -> License:
        return License(self._requester, self._data["mainPrototype"])

    @cached_property
    def _main_prototype_id(self: Self) -> int:
        return self._data["mainPrototype"]["id"]


class BundlesNode(PaginatedAccessor[Bundle, None]):
    class_type = Bundle

    def __init__(self: Self, path: Endpoint, requester: Requester, retriever: BundleRetrieverInterface) -> None:
        super().__init__(path, requester)
        self.retriever = retriever

    async def create(self: Self, source: Path | UrlPath, accept_license: bool = False) -> Bundle:  # noqa: FBT001, FBT002
        if isinstance(source, UrlPath):
            file_content = await self.retriever.download_external_bundle(source)
            files = {"file": file_content}
        else:
            files = {"file": Path(source).read_bytes()}

        response = await self._requester.post("bundles", data=files)

        bundle = Bundle(requester=self._requester, data=response.as_dict())

        if accept_license and bundle.license.state == "unaccepted":
            await bundle.license.accept()

        return bundle

    def get_own_path(self: Self) -> Endpoint:
        return ("bundles",)


class Cluster(
    WithStatus,
    Deletable,
    WithActions,
    WithUpgrades,
    WithConfig,
    WithActionHostGroups,
    WithConfigHostGroups,
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

    @async_cached_property
    async def mapping(self: Self) -> ClusterMapping:
        return await ClusterMapping.for_cluster(owner=self)

    @cached_property
    def services(self: Self) -> "ServicesNode":
        return ServicesNode(parent=self, path=(*self.get_own_path(), "services"), requester=self._requester)

    @cached_property
    def hosts(self: Self) -> "HostsInClusterNode":
        return HostsInClusterNode(path=(*self.get_own_path(), "hosts"), requester=self._requester)

    @cached_property
    def imports(self: Self) -> ClusterImports:
        return ClusterImports()


class ClustersNode(PaginatedAccessor[Cluster, None]):
    class_type = Cluster

    async def create(self: Self, bundle: Bundle, name: str, description: str = "") -> Cluster:
        response = await self._requester.post(
            "clusters", data={"prototypeId": bundle._main_prototype_id, "name": name, "description": description}
        )

        return Cluster(requester=self._requester, data=response.as_dict())


class Service(
    WithStatus,
    Deletable,
    WithActions,
    WithConfig,
    WithActionHostGroups,
    WithConfigHostGroups,
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

    @cached_property
    def components(self: Self) -> "ComponentsNode":
        return ComponentsNode(parent=self, path=(*self.get_own_path(), "components"), requester=self._requester)

    @property
    def license(self: Self) -> License:
        return License(self._requester, self._data)


class ServicesNode(PaginatedChildAccessor[Cluster, Service, None]):
    class_type = Service

    def _get_ids_and_license_state_by_filter(
        self: Self,
        service_prototypes: dict,
    ) -> dict[int, str]:
        # todo: implement retrieving of ids when filter is implemented
        if not service_prototypes:
            raise NotFoundError
        return {s["id"]: s["license"]["status"] for s in service_prototypes}

    async def add(
        self: Self,
        accept_license: bool = False,  # noqa: FBT001, FBT002
    ) -> Service:
        candidates_prototypes = (
            await self._requester.get(*self._parent.get_own_path(), "service-candidates")
        ).as_dict()
        services_data = self._get_ids_and_license_state_by_filter(candidates_prototypes)
        if accept_license:
            for prototype_id, license_status in services_data.items():
                if license_status == "unaccepted":
                    await self._requester.post("prototypes", prototype_id, "license", "accept", data={})

        response = await self._requester.post(
            "services", data=[{"prototypeId": prototype_id} for prototype_id in services_data]
        )

        return Service(data=response.as_dict(), parent=self._parent)


class Component(
    WithStatus, WithActions, WithConfig, WithActionHostGroups, WithConfigHostGroups, InteractiveChildObject[Service]
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


class ComponentsNode(PaginatedChildAccessor[Service, Component, None]):
    class_type = Component


class HostProvider(Deletable, WithActions, WithUpgrades, WithConfig, WithConfigHostGroups, RootInteractiveObject):
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


class HostProvidersNode(PaginatedAccessor[HostProvider, None]):
    class_type = HostProvider

    async def create(self: Self, bundle: Bundle, name: str, description: str = "") -> HostProvider:
        response = await self._requester.post(
            "hostproviders", data={"prototypeId": bundle._main_prototype_id, "name": name, "description": description}
        )

        return HostProvider(requester=self._requester, data=response.as_dict())


class Host(Deletable, WithActions, WithStatus, WithMaintenanceMode, RootInteractiveObject):
    PATH_PREFIX = "hosts"

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        return str(self._data["description"])

    @async_cached_property
    async def cluster(self: Self) -> Cluster | None:
        if not self._data["cluster"]:
            return None
        return await Cluster.with_id(requester=self._requester, object_id=self._data["cluster"]["id"])

    @async_cached_property
    async def hostprovider(self: Self) -> HostProvider:
        return await HostProvider.with_id(requester=self._requester, object_id=self._data["hostprovider"]["id"])


class HostsAccessor(PaginatedAccessor[Host, None]):
    class_type = Host


class HostsNode(HostsAccessor):
    async def create(
        self: Self, provider: HostProvider, name: str, description: str, cluster: Cluster | None = None
    ) -> None:
        data = {"hostproviderId": provider.id, "name": name, "description": description}
        if cluster:
            data["clusterId"] = cluster.id
        await self._requester.post(*self._path, data=data)


class HostsInClusterNode(HostsAccessor):
    async def add(self: Self, host: Host | Iterable[Host] | None = None, filters: Filter | None = None) -> None:
        hosts = await self._get_hosts_from_arg_or_filter(host=host, filters=filters)

        await self._requester.post(*self._path, data=[{"hostId": host.id} for host in hosts])

    async def remove(self: Self, host: Host | Iterable[Host] | None = None, filters: Filter | None = None) -> None:
        hosts = await self._get_hosts_from_arg_or_filter(host=host, filters=filters)

        error = await safe_gather(
            coros=(self._requester.delete(*self._path, host_.id) for host_ in hosts),
            msg="Some hosts can't be deleted from cluster",
        )

        if error is not None:
            raise error

    async def _get_hosts_from_arg_or_filter(
        self: Self, host: Host | Iterable[Host] | None = None, filters: Filter | None = None
    ) -> list[Host]:
        if all((host, filters)):
            raise ValueError("`host` and `filters` arguments are mutually exclusive.")

        if host:
            hosts = list(host) if isinstance(host, Iterable) else [host]
        else:
            hosts = await self.filter(filters)  # type: ignore  # TODO

        return hosts


class Job[Object: "InteractiveObject"](WithStatus, WithActions, WithJobStatus, RootInteractiveObject):
    PATH_PREFIX = "tasks"

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def start_time(self: Self) -> datetime:
        return self._data["startTime"]

    @property
    def finish_time(self: Self) -> datetime:
        return self._data["endTime"]

    @property
    def object(self: Self) -> Object:
        obj_data = self._data["objects"][0]
        obj_type = obj_data["type"]

        obj_dict = {
            "host": Host,
            "component": Component,
            "provider": HostProvider,
            "cluster": Cluster,
            "service": Service,
            "adcm": ADCM,
        }

        return self._construct(what=obj_dict[obj_type], from_data=obj_data)

    @property
    def action(self: Self) -> Action:
        return self._construct(what=Action, from_data=self._data["action"])

    async def wait(self: Self, status_predicate: Callable[[], bool], timeout: int = 30, poll: int = 5) -> None:
        if self._data["status"] not in (JobStatus.RUNNING, JobStatus.CREATED):
            return

        for _ in range(timeout // poll):
            await asyncio.sleep(poll)
            if status_predicate():
                self._data["status"] = self.get_status()
                return

    async def terminate(self: Self) -> None:
        await self._requester.post(*self.get_own_path(), "terminate", data={})
