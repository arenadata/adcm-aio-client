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

import pytest

from adcm_aio_client import ADCMSession, Filter
from adcm_aio_client.config import Parameter
from tests.integration.examples.conftest import CREDENTIALS, REQUEST_KWARGS
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


async def test_cluster(adcm: ADCMContainer) -> None:
    """
    Cluster (`client.clusters`) API Examples:
        - upload from path
        - retrieval with filtering / all clusters
        - cluster removal
        - change of mapping between hosts and components by cluster
        - update of cluster config
        - upgrade of cluster
        - running of cluster action
    """
    async with ADCMSession(url=adcm.url, credentials=CREDENTIALS, **REQUEST_KWARGS) as client:
        simple_cluster = await client.clusters.create(
            bundle=await client.bundles.get(name__eq="Simple Cluster"), name="simple_cluster"
        )
        complex_cluster = await client.clusters.create(
            bundle=await client.bundles.get(name__eq="Some Cluster", version__eq="0.1"), name="complex_cluster"
        )

        # getting full list of clusters
        clusters = await client.clusters.all()
        assert len(clusters) == 2

        # getting filtered list of clusters
        clusters = await client.clusters.filter(name__contains="complex")
        assert len(clusters) == 1

        # deletion of cluster
        await simple_cluster.delete()

        # mapping change
        provider = await client.hostproviders.create(
            bundle=await client.bundles.get(name__eq="simple_provider"), name="simple_provider"
        )
        host_1 = await client.hosts.create(hostprovider=provider, name="host-1", cluster=complex_cluster)
        host_2 = await client.hosts.create(hostprovider=provider, name="host-2", cluster=complex_cluster)

        service, *_ = await complex_cluster.services.add(Filter(attr="name", op="eq", value="example_1"))
        service_component = await service.components.get(name__eq="first")

        cluster_mapping = await complex_cluster.mapping

        await cluster_mapping.add(component=service_component, host=(host_1, host_2))
        await cluster_mapping.save()

        # config change. The option is also available to Service, Component, Hostprovider, Host, Action
        config = await complex_cluster.config
        config["string_field_prev", Parameter].set("new string value to save")
        await config.save()

        # running of upgrade
        upgrade = await complex_cluster.upgrades.get(name__eq="Simple")
        await upgrade.run()

        # running of action. The option is also available to Service, Component, Hostprovider, Host
        action = await complex_cluster.actions.get(name__eq="success")
        await action.run()
