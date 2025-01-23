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

from adcm_aio_client import ADCMSession
from tests.integration.examples.conftest import CREDENTIALS, REQUEST_KWARGS
from tests.integration.setup_environment import ADCMContainer

pytestmark = [pytest.mark.asyncio]


async def test_hostprovider(adcm: ADCMContainer) -> None:
    """
    Hostprovider (`client.hostproviders`) API Examples:
        - upload from path
        - retrieval with filtering / all hostproviders
        - hostprovider removal
        - creation of new hosts by hostprovider
        - retrieval a list of hosts by hostprovider with filtering / all hosts
        - upgrade of hostprovider
    """
    async with ADCMSession(url=adcm.url, credentials=CREDENTIALS, **REQUEST_KWARGS) as client:
        # adding new hostprovider
        hostprovider = await client.hostproviders.create(
            bundle=await client.bundles.get(name__eq="simple_provider"), name="first provider"
        )
        second_hostprovider = await client.hostproviders.create(
            bundle=await client.bundles.get(name__eq="simple_provider"), name="second provider"
        )

        # getting full list of hostproviders
        providers = await client.hostproviders.all()
        assert len(providers) == 2

        # getting filtered list of hostproviders
        providers = await client.hostproviders.filter(name__contains="first")
        assert len(providers) == 1

        # deletion of hostprovider
        await second_hostprovider.delete()

        # adding new hosts by hostprovider
        for i in range(3):
            await client.hosts.create(hostprovider=hostprovider, name=f"host-{i}")

        # getting full list of hosts
        hosts = await hostprovider.hosts.all()
        assert len(hosts) == 3

        # getting filtered list of hosts:
        hosts = await hostprovider.hosts.filter(name__contains="host-2")
        assert len(hosts) == 1

        # running upgrade of hostprovider
        upgrade = await hostprovider.upgrades.get(name__eq="simple_provider")
        await upgrade.run()
