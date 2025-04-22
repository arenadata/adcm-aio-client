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


from functools import cached_property
from typing import Self

from adcm_aio_client.objects import ADCM
from adcm_aio_client.objects._cm import BundlesNode, ClustersNode, HostProvidersNode, HostsNode, JobsNode
from adcm_aio_client.requesters import BundleRetrieverInterface, Requester

MIN_ADCM_VERSION = "2.5.0"


class ADCMClient:
    """
    ADCM client object.<br>
    It's main purpose is to provide access to ADCM objects.<br>
    Can be obtained by entering ADCMSession context manager

    ```python
        async with ADCMSession(url=url, credentials=credentials, **kwargs) as client:
            yield client
    ```
    """

    def __init__(
        self: Self, requester: Requester, bundle_retriever: BundleRetrieverInterface, adcm_version: str
    ) -> None:
        self._requester = requester
        self._retrieve_bundle_from_remote_url = bundle_retriever
        self._adcm_version = adcm_version

    @cached_property
    def clusters(self: Self) -> ClustersNode:
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
        return ClustersNode(path=("clusters",), requester=self._requester)

    @cached_property
    def hosts(self: Self) -> HostsNode:
        """
        Node responsible for accessing `Host` objects.<br>
        Supports filtering by `name`, `status` and `bundle` host's attributes.

        Examples:
        ```python
        # get host which name contains substring `ssh` or `None`, if such host does not exist.
        host: Host | None = await adcm_client.hosts.get_or_none(name__icontains="ssh")
        # get list of hosts which status is not equal to `up`, case-insensitive.
        hosts: list[Host] = await adcm_client.hosts.filter(status__ine="up")
        ```
        """
        return HostsNode(path=("hosts",), requester=self._requester)

    @cached_property
    def hostproviders(self: Self) -> HostProvidersNode:
        """
        Node responsible for accessing `HostProvider` objects.<br>
        Supports filtering by `name` and `bundle` hostprovider's attribute.

        Examples:
        ```python
        # get hostprovider which name contains substring `yandex` or `None`, if such hostprovider does not exist.
        hostprovider: HostProvider | None = await adcm_client.hostproviders.get_or_none(name__icontains="yandex")

        # get list of hostproviders which bundle is not equal to `bundle_object`.
        hostproviders: list[HostProvider] = await adcm_client.hostproviders.filter(
                                                                                    Filter(attr="bundle", op="ne",
                                                                                    value=bundle_object)
                                                                                    )
        ```
        """
        return HostProvidersNode(path=("hostproviders",), requester=self._requester)

    @cached_property
    def adcm(self: Self) -> ADCM:
        """
        Node responsible for accessing `ADCM` object. Represents adcm entity in ADCM terminology
        and corresponding attributes like 'actions' and 'configs'

        ```python
         actions: list[Action] = await adcm_client.adcm.actions.all()
        ```
        """
        return ADCM(requester=self._requester, data={}, version=self._adcm_version)

    @cached_property
    def bundles(self: Self) -> BundlesNode:
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
        return BundlesNode(
            path=("bundles",), requester=self._requester, retriever=self._retrieve_bundle_from_remote_url
        )

    @cached_property
    def jobs(self: Self) -> JobsNode:
        """
        Node responsible for accessing `Job` objects.<br>
        Supports filtering by `name`, `display_name`, `status` or `action` job's attribute.

        Examples:
        ```python
        # get job which display name is equal to `DataNode` or `None`, if such job does not exist.
        job: Job | None = await adcm_client.jobs.get_or_none(display_name__eq="DataNode", status="up")

        # get list of jobs whose status is not equal to `failed`.
        jobs: list[Job] = await adcm_client.jobs.filter(action__exclude=["failed"])
        ```
        """
        return JobsNode(path=("tasks",), requester=self._requester)
