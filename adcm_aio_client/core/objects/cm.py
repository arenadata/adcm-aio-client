from collections import deque
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, AsyncGenerator, Awaitable, Callable, Iterable, Literal, Self
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client.core.actions._objects import Action
from adcm_aio_client.core.errors import InvalidFilterError, NotFoundError
from adcm_aio_client.core.filters import (
    ALL_OPERATIONS,
    COMMON_OPERATIONS,
    Filter,
    FilterBy,
    FilterByDisplayName,
    FilterByName,
    FilterByStatus,
    Filtering,
    FilterValue,
)
from adcm_aio_client.core.host_groups import WithActionHostGroups, WithConfigHostGroups
from adcm_aio_client.core.host_groups.action_group import ActionHostGroup
from adcm_aio_client.core.mapping import ClusterMapping
from adcm_aio_client.core.objects._accessors import (
    PaginatedAccessor,
    PaginatedChildAccessor,
    filters_to_inline,
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
    WithImports,
    WithMaintenanceMode,
    WithStatus,
    WithUpgrades,
)
from adcm_aio_client.core.requesters import BundleRetrieverInterface
from adcm_aio_client.core.types import (
    DEFAULT_JOB_TERMINAL_STATUSES,
    Endpoint,
    Requester,
    URLStr,
    WithProtectedRequester,
)
from adcm_aio_client.core.utils import safe_gather


class ADCM(InteractiveObject, WithActions, WithConfig):
    def __init__(self: Self, requester: Requester, data: dict[str, Any], version: str) -> None:
        super().__init__(requester=requester, data=data)
        self._version = version

    @cached_property
    def id(self: Self) -> int:
        return 1

    @property
    def version(self: Self) -> str:
        return self._version

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


class BundlesNode(PaginatedAccessor[Bundle]):
    class_type = Bundle
    filtering = Filtering(
        FilterByName,
        FilterByDisplayName,
        FilterBy("version", ALL_OPERATIONS, str),
        FilterBy("edition", ALL_OPERATIONS, str),
    )

    def __init__(self: Self, path: Endpoint, requester: Requester, retriever: BundleRetrieverInterface) -> None:
        super().__init__(path, requester)
        self._bundle_retriever = retriever

    async def create(self: Self, source: Path | URLStr, *, accept_license: bool = False) -> Bundle:
        if isinstance(source, Path):
            file = Path(source).read_bytes()
        else:
            file = await self._bundle_retriever.download_external_bundle(source)

        response = await self._requester.post_files("bundles", files={"file": file})

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
    WithImports,
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
        return HostsInClusterNode(cluster=self)


FilterByBundle = FilterBy("bundle", COMMON_OPERATIONS, Bundle)


class ClustersNode(PaginatedAccessor[Cluster]):
    class_type = Cluster
    filtering = Filtering(FilterByName, FilterByBundle, FilterByStatus)

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
    WithImports,
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


class ServicesNode(PaginatedChildAccessor[Cluster, Service]):
    class_type = Service
    filtering = Filtering(FilterByName, FilterByDisplayName, FilterByStatus)
    service_add_filtering = Filtering(FilterByName, FilterByDisplayName)

    async def add(self: Self, filter_: Filter, *, accept_license: bool = False) -> list[Service]:
        candidates = await self._retrieve_service_candidates(filter_=filter_)

        if not candidates:
            message = "No services to add by given filters"
            raise NotFoundError(message)

        if accept_license:
            await self._accept_licenses_safe(candidates)

        return await self._add_services(candidates)

    async def _retrieve_service_candidates(self: Self, filter_: Filter) -> list[dict]:
        query = self.service_add_filtering.to_query(filters=(filter_,))
        response = await self._requester.get(*self._parent.get_own_path(), "service-candidates", query=query)
        return response.as_list()

    async def _accept_licenses_safe(self: Self, candidates: list[dict]) -> None:
        unaccepted: deque[int] = deque()

        for candidate in candidates:
            if candidate["license"]["status"] == "unaccepted":
                unaccepted.append(candidate["id"])

        if unaccepted:
            tasks = (
                self._requester.post("prototypes", prototype_id, "license", "accept", data={})
                for prototype_id in unaccepted
            )
            await asyncio.gather(*tasks)

    async def _add_services(self: Self, candidates: list[dict]) -> list[Service]:
        data = [{"prototypeId": candidate["id"]} for candidate in candidates]
        response = await self._requester.post(*self._parent.get_own_path(), "services", data=data)
        return [Service(data=entry, parent=self._parent) for entry in response.as_list()]


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
            default_query={"componentId": self.id},
        )


class ComponentsNode(PaginatedChildAccessor[Service, Component]):
    class_type = Component
    filtering = Filtering(FilterByName, FilterByDisplayName, FilterByStatus)


class HostProvider(Deletable, WithActions, WithUpgrades, WithConfig, WithConfigHostGroups, RootInteractiveObject):
    PATH_PREFIX = "hostproviders"
    filtering = Filtering(FilterByName, FilterByBundle)

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
        return HostsAccessor(path=("hosts",), requester=self._requester, default_query={"hostproviderName": self.name})


class HostProvidersNode(PaginatedAccessor[HostProvider]):
    class_type = HostProvider
    filtering = Filtering(FilterByName, FilterByBundle)

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


class HostsAccessor(PaginatedAccessor[Host]):
    class_type = Host
    filtering = Filtering(FilterByName, FilterByStatus)


class HostsNode(HostsAccessor):
    async def create(
        self: Self, hostprovider: HostProvider, name: str, description: str = "", cluster: Cluster | None = None
    ) -> None:
        data = {"hostproviderId": hostprovider.id, "name": name, "description": description}
        if cluster:
            data["clusterId"] = cluster.id
        await self._requester.post(*self._path, data=data)


class HostsInClusterNode(HostsAccessor):
    def __init__(self: Self, cluster: Cluster) -> None:
        path = (*cluster.get_own_path(), "hosts")
        super().__init__(path=path, requester=cluster.requester)

        self._root_host_filter = HostsAccessor(path=("hosts",), requester=cluster.requester).filter

    async def add(self: Self, host: Host | Iterable[Host] | Filter) -> None:
        hosts = await self._get_hosts(host=host, filter_func=self._root_host_filter)

        await self._requester.post(*self._path, data=[{"hostId": host.id} for host in hosts])

    async def remove(self: Self, host: Host | Iterable[Host] | Filter) -> None:
        hosts = await self._get_hosts(host=host, filter_func=self.filter)

        error = await safe_gather(
            coros=(self._requester.delete(*self._path, host_.id) for host_ in hosts),
            msg="Some hosts can't be deleted from cluster",
        )

        if error is not None:
            raise error

    async def _get_hosts(
        self: Self, host: Host | Iterable[Host] | Filter, filter_func: Callable[..., Awaitable[list[Host]]]
    ) -> tuple[Host, ...]:
        if isinstance(host, Host):
            hosts = (host,)
        elif isinstance(host, Filter):
            inline_filters = filters_to_inline(host)
            hosts = await filter_func(**inline_filters)
        else:
            hosts = host

        return tuple(hosts)


def default_exit_condition(job: "Job") -> bool:
    return job.get_status() in DEFAULT_JOB_TERMINAL_STATUSES


class Job[Object: "InteractiveObject"](WithStatus, WithActions, RootInteractiveObject):
    PATH_PREFIX = "tasks"

    @property
    def name(self: Self) -> str:
        return str(self._data["name"])

    @property
    def start_time(self: Self) -> datetime | None:
        # todo test it that it should be datetime, not str
        return self._data["startTime"]

    @property
    def finish_time(self: Self) -> datetime | None:
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

    async def wait(
        self: Self,
        timeout: int | None = None,
        poll_interval: int = 10,
        exit_condition: Callable[[Self], bool] = default_exit_condition,
    ) -> Self:
        timeout_condition = datetime.max if timeout is None else (datetime.now() + timedelta(seconds=timeout))  # noqa: DTZ005
        while datetime.now() < timeout_condition:  # noqa: DTZ005
            if exit_condition(self):
                return self
            await asyncio.sleep(poll_interval)

        raise TimeoutError

    async def terminate(self: Self) -> None:
        await self._requester.post(*self.get_own_path(), "terminate", data={})


class JobsNode(PaginatedAccessor[Job]):
    class_type = Job
    filtering = Filtering(
        FilterByName,
        FilterByDisplayName,
        FilterByStatus,
        FilterBy("action", COMMON_OPERATIONS, Action),
        # technical filters, don't use them directly
        FilterBy("target_id", ("eq",), int),
        FilterBy("target_type", ("eq",), str),
    )

    # override accessor methods to allow passing object

    async def get(self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue) -> Job:
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        return await super().get(**all_filters)

    async def get_or_none(self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue) -> Job | None:
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        return await super().get(**all_filters)

    async def filter(self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue) -> list[Job]:
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        return await super().filter(**all_filters)

    async def iter(
        self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue
    ) -> AsyncGenerator[Job, None]:
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        async for entry in super().iter(**all_filters):
            yield entry

    def _prepare_filter_by_object(self: Self, object_: InteractiveObject | None) -> dict:
        if object_ is None:
            return {}

        object_id = object_.id

        if isinstance(object_, (Cluster, Service, Component, Host)):
            object_type = object_.__class__.__name__.lower()
        elif isinstance(object_, HostProvider):
            object_type = "provider"
        elif isinstance(object_, ActionHostGroup):
            object_type = "action-host-group"
        else:
            message = f"Failed to build filter: {object_.__class__.__name__} " "can't be an owner of Job"
            raise InvalidFilterError(message)

        return {"target_id__eq": object_id, "target_type__eq": object_type}
