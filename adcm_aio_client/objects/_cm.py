# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from datetime import datetime, timedelta
from functools import cached_property
from itertools import chain
from pathlib import Path
from typing import Any, Literal, Self
import asyncio

from asyncstdlib.functools import cached_property as async_cached_property  # noqa: N813

from adcm_aio_client._filters import (
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
from adcm_aio_client._types import (
    DEFAULT_JOB_TERMINAL_STATUSES,
    Endpoint,
    Requester,
    URLStr,
    WithProtectedRequester,
)
from adcm_aio_client._utils import safe_gather
from adcm_aio_client.actions._objects import Action
from adcm_aio_client.errors import InvalidFilterError, NotFoundError, WaitTimeoutError
from adcm_aio_client.host_groups._action_group import ActionHostGroup, WithActionHostGroups
from adcm_aio_client.host_groups._config_group import WithConfigHostGroups
from adcm_aio_client.mapping._objects import ClusterMapping
from adcm_aio_client.objects._accessors import (
    PaginatedAccessor,
    PaginatedChildAccessor,
    filters_to_inline,
)
from adcm_aio_client.objects._base import (
    InteractiveChildObject,
    InteractiveObject,
    RootInteractiveObject,
)
from adcm_aio_client.objects._common import (
    Deletable,
    WithActions,
    WithConfig,
    WithImports,
    WithMaintenanceMode,
    WithStatus,
    WithUpgrades,
)
from adcm_aio_client.requesters import BundleRetrieverInterface


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
    """
    Represents `Bundle` entity in ADCM terminology.
    """

    PATH_PREFIX = "bundles"
    """@private"""

    @property
    def name(self: Self) -> str:
        """`Bundle`'s name"""
        return str(self._data["name"])

    @property
    def display_name(self: Self) -> str:
        """`Bundle`'s display_name"""
        return str(self._data["displayName"])

    @property
    def version(self: Self) -> str:
        """`Bundle`'s version"""
        return str(self._data["version"])

    @property
    def edition(self: Self) -> Literal["community", "enterprise"]:
        """`Bundle`'s version (community or enterprise)"""
        return self._data["edition"]

    @property
    def signature_status(self: Self) -> Literal["invalid", "valid", "absent"]:
        """`Bundle`'s signature_status (invalid, valid or absent)"""
        return self._data["signatureStatus"]

    @async_cached_property
    async def license(self: Self) -> License:
        """
        `License` object of this bundle
        """
        return License(self._requester, self._data["mainPrototype"])

    @property
    def _type(self: Self) -> Literal["cluster", "provider"]:
        return self._data["mainPrototype"]["type"]

    @cached_property
    def _main_prototype_id(self: Self) -> int:
        return self._data["mainPrototype"]["id"]


class BundlesNode(PaginatedAccessor[Bundle]):
    """
    Node responsible for accessing `Bundle` objects.<br>
    Supports filtering by `name`, `display_name`, `version` or `edition` bundle's attribute.

    Examples:
    ```python
    # get bundle which name contains substring `adh` or `None`, if such bundle does not exist.
    bundle: Bundle | None = await adcm_client.bundles.get_or_none(name__contains="adh")

    # get list of bundles with version `0.1-alpha`.
    bundle: list[Bundle] = await adcm_client.bundles.filter(Filter(attr="version", op="eq", value="0.1-alpha"))

    # get list of bundles with `edition` is `enterprise`.
    bundle: list[Bundle] = await adcm_client.bundles.filter(edition__eq="enterprise")
    ```
    """

    class_type = Bundle
    """@private"""
    filtering = Filtering(
        FilterByName,
        FilterByDisplayName,
        FilterBy("version", ALL_OPERATIONS, str),
        FilterBy("edition", ALL_OPERATIONS, str),
    )
    """@private"""

    def __init__(self: Self, path: Endpoint, requester: Requester, retriever: BundleRetrieverInterface) -> None:
        """@private"""
        super().__init__(path, requester)
        self._bundle_retriever = retriever

    async def create(self: Self, source: Path | URLStr, *, accept_license: bool = False) -> Bundle:
        """
        Create new `Bundle` object.
        :param source: path to bundle archive or url to download bundle
        :param accept_license: If set to `True`, bundle's license will be accepted on creation.
                               It can be accepted later via bundle's `license` attribute
        :return: `Bundle` object
        """
        if isinstance(source, Path):
            file = Path(source).read_bytes()
        else:
            file = await self._bundle_retriever.download_external_bundle(source)

        response = await self._requester.post_files("bundles", files={"file": file})

        bundle = Bundle(requester=self._requester, data=response.as_dict())

        if accept_license:
            license_ = await bundle.license
            if license_.state == "unaccepted":
                await license_.accept()

        return bundle

    def get_own_path(self: Self) -> Endpoint:
        """@private"""
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
    """
    Represents `Cluster` entity in ADCM terminology.
    """

    PATH_PREFIX = "clusters"
    """@private"""

    # data-based properties

    @property
    def name(self: Self) -> str:
        """
        `Cluster`'s name.
        """
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        """
        `Cluster`'s description.
        """
        return str(self._data["description"])

    # related/dynamic data access

    @async_cached_property
    async def bundle(self: Self) -> Bundle:
        """
        `Bundle` object in which `Cluster` is defined.
        """
        prototype_id = self._data["prototype"]["id"]
        response = await self._requester.get("prototypes", prototype_id)

        bundle_id = response.as_dict()["bundle"]["id"]
        response = await self._requester.get("bundles", bundle_id)

        return self._construct(what=Bundle, from_data=response.as_dict())

    # object-specific methods

    async def set_ansible_forks(self: Self, value: int) -> Self:
        """
        Sets the `defaults.forks` parameter value for `Cluster`'s ansible config.
        :param value: integer
        """
        await self._requester.post(
            *self.get_own_path(), "ansible-config", data={"config": {"defaults": {"forks": value}}, "adcmMeta": {}}
        )
        return self

    # nodes and managers to access

    @async_cached_property
    async def mapping(self: Self) -> ClusterMapping:
        """
        Through this node you can change `Cluster`'s mapping.
        """
        return await ClusterMapping.for_cluster(owner=self)

    @cached_property
    def services(self: Self) -> "ServicesNode":
        """
        Group of related `Service`s.
        """
        return ServicesNode(parent=self, path=(*self.get_own_path(), "services"), requester=self._requester)

    @cached_property
    def hosts(self: Self) -> "HostsInClusterNode":
        """
        Group of `Host`s linked to this `Cluster`.
        """
        return HostsInClusterNode(cluster=self)


FilterByBundle = FilterBy("bundle", COMMON_OPERATIONS, Bundle)
"""@private"""


class ClustersNode(PaginatedAccessor[Cluster]):
    """
    Node responsible for accessing `Cluster` objects.<br>
    Supports filtering by `name`, `bundle` or `status` cluster's attribute.

    Examples:
    ```python
    # get cluster which name contains substring `adh` or `None`, if such cluster does not exist.
    cluster: Cluster | None = await adcm_client.clusters.get_or_none(name__icontains="adh")

    # get list of clusters which bundle is not equal to `bundle_object`.
    clusters: list[Cluster] = await adcm_client.clusters.filter(Filter(attr="bundle", op="ne", value=bundle_object))

    # get list of clusters with status not equal to `up` or `down`.
    clusters: list[Cluster] = await adcm_client.clusters.filter(status__exclude=["up", "down"])
    ```
    """

    class_type = Cluster
    """@private"""
    filtering = Filtering(FilterByName, FilterByBundle, FilterByStatus)
    """@private"""

    async def create(self: Self, bundle: Bundle, name: str, description: str = "") -> Cluster:
        """
        Create new `Cluster` object
        :param bundle: `Bundle` object in which cluster is defined
        :param name: str, cluster's name
        :param description: str, cluster's description. Defaults to empty string
        :return: `Cluster` object
        """
        response = await self._requester.post(
            "clusters",
            data={
                "prototypeId": bundle._main_prototype_id,
                "name": name,
                "description": description,
            },
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
    WithMaintenanceMode,
    InteractiveChildObject[Cluster],
):
    """
    Represents part of `Cluster` named `Service` in ADCM terminology.

    Can be "standalone" entity (like `Spark Client`)
    or a group of related `Component`s that are expected to be mapped on some hosts.

    Adding services is available via `Cluster` API:
    ```python
    cluster: Cluster
    adbcc = await cluster.services.add(Filter(attr="display_name", op="ieq", value="adb control"))
    ```

    Components doesn't require explicit addition/creation,
    so they can be acquired with filters like other objects:
    ```python
    service: Service
    await service.components.get_or_none(name__eq="master")
    ```

    Working with services may include interactions such as:
    - imports management
    - config management
    - action/config host groups
    """

    PATH_PREFIX = "services"
    """@private"""

    @property
    def name(self: Self) -> str:
        """
        `Service`'s name.
        :return: str
        """
        return self._data["name"]

    @property
    def display_name(self: Self) -> str:
        """
        `Service`'s name displayed in UI.
        :return: str
        """
        return self._data["displayName"]

    @cached_property
    def cluster(self: Self) -> Cluster:
        """
        Cluster to which this service belongs
        :return: Cluster
        """
        return self._parent

    @cached_property
    def components(self: Self) -> "ComponentsNode":
        """
        Components Node for accessing components of this service
        :return `ComponentsNode`
        """
        return ComponentsNode(parent=self, path=(*self.get_own_path(), "components"), requester=self._requester)

    @async_cached_property
    async def license(self: Self) -> License:
        """
        `License` object for this service
        :return `License`
        """
        prototype_data = (await self.requester.get("prototypes", self._data["prototype"]["id"])).as_dict()
        return License(self._requester, prototype_data)


class ServicesNode(PaginatedChildAccessor[Cluster, Service]):
    """
    Node for accessing `Service` objects and managing them.

    Example of using:
    ```python
    # Add service with name containing "yarn"
    service: Service = await cluster.services.add(Filter(attr="name", op="contains", value="yarn"))

    # Get service by name
    service: Service = await cluster.services.get(name__eq="yarn")

    # List all services
    services: list[Service] = await cluster.services.list()

    ```
    """

    class_type = Service
    filtering = Filtering(FilterByName, FilterByDisplayName, FilterByStatus)
    service_add_filtering = Filtering(FilterByName, FilterByDisplayName)

    async def add(
        self: Self, filter_: Filter, *, accept_license: bool = False, with_dependencies: bool = False
    ) -> list[Service]:
        """
        Create new `Service` object
        :param filter_: `Filter` instance to retrieve required service candidates from the others
        :param accept_license: Accept license for the service
        :param with_dependencies: Retrieve dependencies for the service
        :return: Created `Service` instance
        """
        candidates = await self._retrieve_service_candidates(filter_=filter_)

        if not candidates:
            message = "No services to add by given filters"
            raise NotFoundError(message)

        if with_dependencies:
            dependencies_candidates = await self._find_missing_service_dependencies(candidates)
            candidates.extend(dependencies_candidates)

        if accept_license:
            await self._accept_licenses_safe(candidates)

        return await self._add_services(candidates)

    async def _retrieve_service_candidates(self: Self, filter_: Filter) -> list[dict]:
        """
        Retrieve service candidates
        :param filter_: `Filter` instance to retrieve required service candidate from the others
        :return: list of service candidates as dicts
        """
        query = self.service_add_filtering.to_query(filters=(filter_,))
        response = await self._requester.get(*self._parent.get_own_path(), "service-candidates", query=query)
        return response.as_list()

    async def _find_missing_service_dependencies(self: Self, candidates: list[dict]) -> list[dict]:
        """
        Find missing service dependencies which are still required to have in order to create new `Service` instance
        :param candidates: list of service candidates as dicts.
        Candidates should be obtained by `_retrieve_service_candidates`
        :return: list of service dependencies prototypes as dicts
        """
        response = await self._requester.get(*self._parent.get_own_path(), "service-prototypes")
        all_service_prototypes = response.as_list()

        dependencies = {
            proto["id"]: {dep["servicePrototype"]["id"] for dep in (proto["dependOn"] or ())}
            for proto in all_service_prototypes
        }

        candidate_ids = {c["id"] for c in candidates}

        all_candidate_dependencies = self._detect_missing_dependencies(
            dependencies=dependencies, to_add=candidate_ids, processed=set()
        )
        missing_dependencies = all_candidate_dependencies - candidate_ids

        return [proto for proto in all_service_prototypes if proto["id"] in missing_dependencies]

    def _detect_missing_dependencies(
        self: Self, dependencies: dict[int, set[int]], to_add: set[int], processed: set[int]
    ) -> set[int]:
        """
        Locate missing dependencies
        :param dependencies: the dict consists of prototype id and its dependent prototypes as a set of ids
        :param to_add: the set of prototype ids to be added
        :param processed: the set of prototype ids already processed so there is no need to do it second time
        :return: the set of prototype ids of missing dependencies
        """
        unprocessed = to_add - processed
        if not unprocessed:
            return to_add

        deps_of_unprocessed = set(chain.from_iterable(map(dependencies.__getitem__, unprocessed)))
        if not deps_of_unprocessed:
            return to_add

        return self._detect_missing_dependencies(
            dependencies=dependencies, to_add=to_add | deps_of_unprocessed, processed=processed | unprocessed
        )

    async def _accept_licenses_safe(self: Self, candidates: list[dict]) -> None:
        """
        For each unaccepted license of passed candidates accept it
        :param candidates: list of service candidates as dicts.
        Candidates should be obtained by `_retrieve_service_candidates`
        :return: None
        """
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
        """
        Add services
        :param candidates: list of service candidates dicts obtained by `_retrieve_service_candidates`
        :return: list of created `Service` objects
        """
        data = [{"prototypeId": candidate["id"]} for candidate in candidates]
        response = await self._requester.post(*self._parent.get_own_path(), "services", data=data)
        return [Service(data=entry, parent=self._parent) for entry in response.as_list()]


class Component(
    WithStatus,
    WithActions,
    WithConfig,
    WithActionHostGroups,
    WithConfigHostGroups,
    WithMaintenanceMode,
    InteractiveChildObject[Service],
):
    PATH_PREFIX = "components"
    """
    @private
    """

    @property
    def name(self: Self) -> str:
        """
        `Component`'s name.
        """
        return self._data["name"]

    @property
    def display_name(self: Self) -> str:
        """
        `Component`'s name displayed in UI.
        """
        return self._data["displayName"]

    @async_cached_property
    async def constraint(self: Self) -> list[int | str]:
        """
        `Component`'s constraints on hosts mapping as list of `int` and/or `str` constraint tokens. Possible values:
        [1] — exactly one component should be installed.
        [0,1] — one or zero components should be installed.
        [1,2] — one or two components should be installed.
        [0,+] — zero or any more components should be installed (default value).
        [1,odd] — one or more components should be installed; the total amount should be odd.
        [0,odd] — zero or more components should be installed; if more than zero, the total amount should be odd.
        [odd] — same as [1,odd].
        [1,+] — one or more components should be installed.
        [+] — component should be installed on all hosts of a cluster.
        :return: list of `int` and/or `str`
        """
        response = (await self._requester.get(*self.cluster.get_own_path(), "mapping", "components")).as_list()
        for component in response:
            if component["id"] == self.id:
                return component["constraints"]

        raise NotFoundError

    @cached_property
    def service(self: Self) -> Service:
        """
        `Component`'s parent `Service` it belongs to.
        """
        return self._parent

    @cached_property
    def cluster(self: Self) -> Cluster:
        """
        `Component`'s parent `Cluster` it belongs to.
        """
        return self.service.cluster

    @cached_property
    def hosts(self: Self) -> "HostsAccessor":
        """
        `HostsAccessor` for `Component`'s hosts.
        """
        return HostsAccessor(
            path=(*self.cluster.get_own_path(), "hosts"),
            requester=self._requester,
            default_query={"componentId": self.id},
        )


class ComponentsNode(PaginatedChildAccessor[Service, Component]):
    """
    Node responsible for accessing `Components` objects.<br>
    Supports filtering by `name`, `display_name` or `status` component's attributes.

    Examples:
    ```python
    # get components which display name is equal to `DataNode` or `None`, if such component does not exist.
    component: Component | None = await service.components.get_or_none(display_name__eq="DataNode", status="up")

    # get list of components whose status is not equal to `up` or `down`.
    components: list[Component] = await service.components.filter(status__exclude=["up", "down"])
    ```
    """

    class_type = Component
    """
    @private
    """
    filtering = Filtering(FilterByName, FilterByDisplayName, FilterByStatus)
    """
    @private
    """


class HostProvider(Deletable, WithActions, WithUpgrades, WithConfig, WithConfigHostGroups, RootInteractiveObject):
    """
    Represents `HostProvider` entity in ADCM terminology.
    """

    PATH_PREFIX = "hostproviders"
    """@private"""
    filtering = Filtering(FilterByName, FilterByBundle)
    """@private"""

    # data-based properties

    @property
    def name(self: Self) -> str:
        """
        `HostProvider`'s name.
        """
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        """
        `HostProvider`'s description.
        """
        return str(self._data["description"])

    @property
    def display_name(self: Self) -> str:
        """
        `HostProvider`'s display name.
        """
        return str(self._data["prototype"]["displayName"])

    @cached_property
    def hosts(self: Self) -> "HostsAccessor":
        """
        Group of related `Host`s.
        :return: `HostsAccessor` object
        """
        return HostsAccessor(path=("hosts",), requester=self._requester, default_query={"hostproviderName": self.name})


class HostProvidersNode(PaginatedAccessor[HostProvider]):
    """
    Node responsible for accessing `HostProvider` objects.<br>
    Supports filtering by `name` and `bundle` hostprovider's attributes.

    Examples:
    ```python
    # get hostprovider which name contains substring `yandex` or `None`, if such hostprovider does not exist.
    hostprovider: HostProvider | None = await adcm_client.hostproviders.get_or_none(name__icontains="yandex")

    # get list of hostproviders which bundle is not equal to `bundle_object`.
    hostproviders: list[HostProvider] = await adcm_client.hostproviders.filter(Filter(attr="bundle", op="ne", value=bundle_object))
    ```
    """  # noqa: E501

    class_type = HostProvider
    """@private"""
    filtering = Filtering(FilterByName, FilterByBundle)
    """@private"""

    async def create(self: Self, bundle: Bundle, name: str, description: str = "") -> HostProvider:
        """
        Create new `HostProvider` object
        :param bundle: `Bundle` object in which hostprovider is defined
        :param name: hostprovider's name
        :param description: hostprovider's description
        :return: `HostProvider` object
        """
        response = await self._requester.post(
            "hostproviders",
            data={
                "prototypeId": bundle._main_prototype_id,
                "name": name,
                "description": description,
            },
        )

        return HostProvider(requester=self._requester, data=response.as_dict())


class Host(Deletable, WithActions, WithConfig, WithStatus, WithMaintenanceMode, RootInteractiveObject):
    """
    Represents `Host` entity in ADCM terminology.
    """

    PATH_PREFIX = "hosts"
    """@private"""

    @property
    def name(self: Self) -> str:
        """`Host`'s name"""
        return str(self._data["name"])

    @property
    def description(self: Self) -> str:
        """`Host`'s description"""
        return str(self._data["description"])

    @async_cached_property
    async def cluster(self: Self) -> Cluster | None:
        """
        `Cluster` to which the host is linked
        :return: `Cluster` or `None` if host is not linked to any cluster
        """
        if not self._data["cluster"]:
            return None

        return await Cluster.with_id(requester=self._requester, object_id=self._data["cluster"]["id"])

    @async_cached_property
    async def hostprovider(self: Self) -> HostProvider:
        """`HostProvider` from which the host was created"""
        return await HostProvider.with_id(requester=self._requester, object_id=self._data["hostprovider"]["id"])


class HostsAccessor(PaginatedAccessor[Host]):
    """
    Node responsible for accessing `Host` objects.<br>
    Supports filtering by `name`, `status` and `bundle` host's attributes.

    Examples:
    ```python
    # get host mapped to `component` which name contains substring `ssh` or `None`, if such host does not exist.
    host: Host | None = await component.hosts.get_or_none(name__icontains="ssh")

    # get list of hosts that belongs to `hostprovider` and their bundle is not equal to `bundle_object`.
    hosts: list[Host] = await hostprovider.filter(Filter(attr="bundle", op="ne", value=bundle_object))
    ```
    """

    class_type = Host
    """@private"""
    filtering = Filtering(FilterByName, FilterByStatus, FilterBy("hostprovider", COMMON_OPERATIONS, HostProvider))
    """@private"""


class HostsNode(HostsAccessor):
    """
    Node responsible for accessing `Host` objects.<br>
    Supports filtering by `name`, `status` and `bundle` host's attributes.

    Examples:
    ```python
    # get host which name contains substring `ssh` or `None`, if such host does not exist.
    host: Host | None = await adcm_client.hosts.get_or_none(name__icontains="ssh")

    # get list of hosts which status is not equal to `up`, case-insensitive.
    hosts: list[Host] = await adcm_client.filter(status__ine="up")
    ```
    """

    async def create(
        self: Self, hostprovider: HostProvider, name: str, description: str = "", cluster: Cluster | None = None
    ) -> Host:
        """
        Create new `Host` object
        :param hostprovider: `Hostprovider` object, to which created host will belong
        :param name: host's name
        :param description: host's description
        :param cluster: `Cluster` object or None. If specified, links created host to `cluster`
        :return: `Host` object
        """
        data = {"hostproviderId": hostprovider.id, "name": name, "description": description}
        if cluster:
            data["clusterId"] = cluster.id

        response = await self._requester.post(*self._path, data=data)
        return Host(requester=self._requester, data=response.as_dict())


class HostsInClusterNode(HostsAccessor):
    """
    Node responsible for accessing `Host` objects linked to specific `Cluster`.<br>
    Supports filtering by `name`, `status` and `bundle` host's attributes.

    Example:
    ```python
    # get host in `cluster` which name equals to `host-1`
    host: Host = await cluster.hosts.get(name__eq="host-1")
    ```
    """

    def __init__(self: Self, cluster: Cluster) -> None:
        """@private"""
        path = (*cluster.get_own_path(), "hosts")
        super().__init__(path=path, requester=cluster.requester)

        self._root_host_filter = HostsAccessor(path=("hosts",), requester=cluster.requester).filter

    async def add(self: Self, host: Host | Iterable[Host] | Filter) -> None:
        """
        Link specified `host` to `cluster`.
        :param host: `Host` object, iterable of `Host` objects or `Filter` object that describes desired set of `Host`s

        Examples:
        ```python
        await cluster.hosts.add(host=host)
        await cluster.hosts.add(host=[host1, host2, host3])
        await cluster.hosts.add(host=Filter(attr="name", op="eq", value="host-2"))
        ```
        """
        hosts = await self._get_hosts(host=host, filter_func=self._root_host_filter)

        await self._requester.post(*self._path, data=[{"hostId": host.id} for host in hosts])

    async def remove(self: Self, host: Host | Iterable[Host] | Filter) -> None:
        """
        Unlink specified `host` from `cluster`.
        :param host: `Host` object, iterable of `Host` objects or `Filter` object that describes desired set of `Host`s

        Examples:
        ```python
        await cluster.hosts.remove(host=host)
        await cluster.hosts.remove(host=[host1, host2, host3])
        await cluster.hosts.remove(host=Filter(attr="name", op="eq", value="host-2"))
        ```
        """
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


async def default_exit_condition(job: "Job") -> bool:
    """@private"""
    return await job.get_status() in DEFAULT_JOB_TERMINAL_STATUSES


class Job(WithStatus, RootInteractiveObject):
    """
    Represents `Job` entity in ADCM terminology.
    """

    PATH_PREFIX = "tasks"
    """@private"""

    @property
    def name(self: Self) -> str:
        """`Job`'s name."""
        return str(self._data["name"])

    @property
    def display_name(self: Self) -> str:
        """`Job`'s display_name."""
        return str(self._data["displayName"])

    @cached_property
    def start_time(self: Self) -> datetime | None:
        """`Job`'s start_time."""
        time = self._data["startTime"]
        if time is None:
            return time

        return datetime.fromisoformat(time)

    @cached_property
    def finish_time(self: Self) -> datetime | None:
        """`Job`'s finish_time."""
        time = self._data["endTime"]
        if time is None:
            return time

        return datetime.fromisoformat(time)

    @async_cached_property
    async def object(self: Self) -> InteractiveObject:
        """
        Object on which this `Job` is running.
        Can be `Cluster`, `Service`, `Component`, `HostProvider`, `Host` or `ActionHostGroup`.
        """
        objects_raw = self._parse_objects()
        return await self._retrieve_target(objects_raw)

    @async_cached_property
    async def action(self: Self) -> Action:
        """Action in which this `Job` is defined."""
        target = await self.object
        return Action(parent=target, data=self._data["action"])

    async def wait(
        self: Self,
        timeout: int | None = None,
        poll_interval: int = 10,
        exit_condition: Callable[[Self], Awaitable[bool]] = default_exit_condition,
    ) -> Self:
        """
        Wait for `Job` to complete.
        :param timeout: If the Job is not completed after the `timeout`, the `WaitTimeoutError` is raised
        :param poll_interval: The interval at which the `Job`'s exit condition is checked
        :param exit_condition: Callable of one argument - `self`. Calls on each iteration to check if the `Job`
                               reached desired condition. Check `self._data` to see `Job`'s attributes
        """
        timeout_condition = datetime.max if timeout is None else (datetime.now() + timedelta(seconds=timeout))  # noqa: DTZ005

        while datetime.now() < timeout_condition:  # noqa: DTZ005
            if await exit_condition(self):
                return self

            await asyncio.sleep(poll_interval)

        message = "Failed to meet exit condition for job"
        if timeout:
            message = f"{message} in {timeout} seconds with {poll_interval} second interval"

        raise WaitTimeoutError(message)

    async def terminate(self: Self) -> None:
        """Stop execution of this `Job`."""
        await self._requester.post(*self.get_own_path(), "terminate", data={})

    def _parse_objects(self: Self) -> dict[str, int]:
        return {entry["type"]: entry["id"] for entry in self._data["objects"]}

    async def _retrieve_target(self: Self, objects: dict[str, int]) -> InteractiveObject:
        match objects:
            case {"action_host_group": id_}:
                objects.pop("action_host_group")
                owner = await self._retrieve_target(objects)
                return await ActionHostGroup.with_id(parent=owner, object_id=id_)

            case {"host": id_}:
                return await Host.with_id(requester=self._requester, object_id=id_)

            case {"component": id_}:
                objects.pop("component")

                owner = await self._retrieve_target(objects)
                if not isinstance(owner, Service):
                    message = f"Incorrect owner for component detected from job data: {owner}"
                    raise TypeError(message)

                return await Component.with_id(parent=owner, object_id=id_)

            case {"service": id_}:
                objects.pop("service")

                owner = await self._retrieve_target(objects)
                if not isinstance(owner, Cluster):
                    message = f"Incorrect owner for service detected from job data: {owner}"
                    raise TypeError(message)

                return await Service.with_id(parent=owner, object_id=id_)

            case {"cluster": id_}:
                return await Cluster.with_id(requester=self._requester, object_id=id_)

            case {"provider": id_}:
                return await HostProvider.with_id(requester=self._requester, object_id=id_)
            case _:
                message = f"Failed to detect Job's owner based on {objects}"
                raise RuntimeError(message)


class JobsNode(PaginatedAccessor[Job]):
    """
    Node responsible for accessing `Job` objects.<br>
    Supports filtering by `name`, `status` or `action`, `object` job's attributes.
    """

    class_type = Job
    """@private"""
    filtering = Filtering(
        FilterByName,
        FilterByDisplayName,
        FilterByStatus,
        FilterBy("action", COMMON_OPERATIONS, Action),
        # technical filters, don't use them directly
        FilterBy("target_id", ("eq",), int),
        FilterBy("target_type", ("eq",), str),
    )
    """@private"""

    # override accessor methods to allow passing object

    async def get(self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue) -> Job:  # noqa: A002
        """
        Get single `Job`.
        :param object: Special filter for object on which `Job` is running.
               Can be `Cluster`, `Service`, `Component`, `Host`, `HostProvider` or `ActionHostGroup`
        :param filters: other filters, such as `name`, `status` or `action`
        """
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        return await super().get(**all_filters)

    async def get_or_none(self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue) -> Job | None:  # noqa: A002
        """
        Get single `Job`. Returns `None`, if there are none that match the filters.
        :param object: Special filter for object on which `Job` is running.
               Can be `Cluster`, `Service`, `Component`, `Host`, `HostProvider` or `ActionHostGroup`
        :param filters: other filters, such as `name`, `status` or `action`
        """
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        return await super().get_or_none(**all_filters)

    async def filter(self: Self, *, object: InteractiveObject | None = None, **filters: FilterValue) -> list[Job]:  # noqa: A002
        """
        Get list of `Job`s, satisfying filters.
        :param object: Special filter for object on which `Job` is running.
               Can be `Cluster`, `Service`, `Component`, `Host`, `HostProvider` or `ActionHostGroup`
        :param filters: other filters, such as `name`, `status` or `action`
        """
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        return await super().filter(**all_filters)

    async def iter(
        self: Self,
        *,
        object: InteractiveObject | None = None,  # noqa: A002
        **filters: FilterValue,
    ) -> AsyncGenerator[Job, None]:
        """
        Get generator of `Job`s, satisfying filters.
        :param object: Special filter for object on which `Job` is running.
               Can be `Cluster`, `Service`, `Component`, `Host`, `HostProvider` or `ActionHostGroup`
        :param filters: other filters, such as `name`, `status` or `action`
        """
        object_filter = self._prepare_filter_by_object(object)
        all_filters = filters | object_filter
        async for entry in super().iter(**all_filters):
            yield entry

    def _prepare_filter_by_object(self: Self, object_: InteractiveObject | None) -> dict:
        if object_ is None:
            return {}

        object_id = object_.id

        if isinstance(object_, Cluster | Service | Component | Host):
            object_type = object_.__class__.__name__.lower()
        elif isinstance(object_, HostProvider):
            object_type = "provider"
        elif isinstance(object_, ActionHostGroup):
            object_type = "action_host_group"
        else:
            message = f"Failed to build filter: {object_.__class__.__name__} " "can't be an owner of Job"
            raise InvalidFilterError(message)

        return {"target_id__eq": object_id, "target_type__eq": object_type}
