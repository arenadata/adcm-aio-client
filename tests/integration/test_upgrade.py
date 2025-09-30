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

from pathlib import Path
from typing import NamedTuple

import yaml
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import Parameter, ParameterGroup
from adcm_aio_client.errors import (
    ConfigNoParameterError,
    NoConfigInActionError,
    NoMappingInActionError,
)
from adcm_aio_client.objects import Bundle, HostProvider, Job
from tests.integration.bundle import pack_bundle

pytestmark = [pytest.mark.asyncio]


class Context(NamedTuple):
    client: ADCMClient
    old_bundle: Bundle
    new_bundle: Bundle
    hostprovider: HostProvider


async def upload_hp_bundle_with_50_plus_upgrades(adcm_client: ADCMClient, workdir: Path) -> Bundle:
    # based on simple_hostprovider
    hp_def = {"type": "provider", "name": "simple_provider", "version": 6}
    host_def = {"type": "host", "name": "simple_host", "version": 2}

    upgrade_base = {"versions": {"min": 3, "max": 5}, "states": {"available": "any"}}
    action_base = {"scripts": [{"name": "switch", "script_type": "internal", "script": "bundle_switch"}]}

    simple_upgrades = [{"name": f"simple-{i}"} | upgrade_base for i in range(40)]
    action_upgrades = [{"name": f"action-{i}"} | upgrade_base | action_base for i in range(20)]

    bundle = [hp_def | {"upgrade": simple_upgrades + action_upgrades}, host_def]

    bundle_dir = workdir / "hp_bundle_many_upgrades"
    bundle_dir.mkdir(parents=True)

    config_file = bundle_dir / "config.yaml"
    with config_file.open(mode="w", encoding="utf-8") as f:
        yaml.safe_dump(bundle, f)

    bundle_path = pack_bundle(from_dir=bundle_dir, to=workdir)

    return await adcm_client.bundles.create(source=bundle_path)


@pytest_asyncio.fixture()
async def hostprovider(adcm_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> HostProvider:
    return await adcm_client.hostproviders.create(simple_hostprovider_bundle, name="Simple HP")


@pytest.fixture()
def context(
    adcm_client: ADCMClient,
    previous_complex_cluster_bundle: Bundle,
    complex_cluster_bundle: Bundle,
    hostprovider: HostProvider,
) -> Context:
    return Context(
        client=adcm_client,
        old_bundle=previous_complex_cluster_bundle,
        new_bundle=complex_cluster_bundle,
        hostprovider=hostprovider,
    )


async def test_upgrade_api(context: Context, tmp_path: Path) -> None:
    await _test_simple_upgrade(context)
    await _test_upgrade_with_config(context)
    await _test_upgrade_filtering(context, tmp_path)


async def _test_simple_upgrade(context: Context) -> None:
    cluster = await context.client.clusters.create(context.old_bundle, "for simple")
    service_1, *_ = await cluster.services.add(Filter(attr="name", op="eq", value="example_1"))

    assert (await cluster.bundle).id == context.old_bundle.id
    assert len(await service_1.components.all()) == 2

    upgrade = await cluster.upgrades.get(name__eq="Simple")
    assert upgrade.name == "Simple"
    assert upgrade.display_name == "I am very simple, you know?"

    bundle_from_upgrade = await upgrade.bundle
    assert bundle_from_upgrade.id == context.new_bundle.id
    assert bundle_from_upgrade.display_name == context.new_bundle.display_name

    with pytest.raises(NoMappingInActionError):
        await upgrade.mapping

    with pytest.raises(NoConfigInActionError):
        await upgrade.config

    result = await upgrade.run()
    assert result is None

    upgrades = await cluster.upgrades.all()
    assert upgrades == []

    assert (await cluster.bundle).id == context.old_bundle.id
    await cluster.refresh()
    assert (await cluster.bundle).id == context.new_bundle.id

    assert service_1.display_name == "Old naMe"
    assert len(await service_1.components.all()) == 3
    await service_1.refresh()
    assert service_1.display_name == "First Example"


async def _test_upgrade_with_config(context: Context) -> None:
    cluster = await context.client.clusters.create(context.old_bundle, "for config")

    upgrades = await cluster.upgrades.filter(display_name__contains="With action")
    assert len(upgrades) == 1
    upgrade = await cluster.upgrades.get_or_none(display_name__in=["With action and config"])
    assert upgrade is not None

    with pytest.raises(NoMappingInActionError):
        await upgrade.mapping

    config = await upgrade.config
    config["string_field", Parameter].set("useless yet required")

    payload = config["Request Body", Parameter]
    assert payload.value == [1, {"k": "v"}, "plain"]
    payload.set({"value": payload.value})

    group = config["Some Params", ParameterGroup]
    with pytest.raises(ConfigNoParameterError):
        group["cant_find"]
    inner_group = group["Filter"]
    assert isinstance(inner_group, ParameterGroup)
    assert inner_group["quantity", Parameter].value == 14443
    assert inner_group["nested"]["op"].value == "eq"  # type: ignore
    assert inner_group["nested"]["attr"].set("awesome")  # type: ignore

    upgrade.verbose = True
    job = await upgrade.run()
    assert isinstance(job, Job)

    await cluster.refresh()
    # job's not finished
    assert (await cluster.bundle).id == context.old_bundle.id

    await job.wait(timeout=30)
    await cluster.refresh()
    assert (await cluster.bundle).id == context.new_bundle.id


async def _test_upgrade_filtering(context: Context, tmp_path: Path) -> None:
    hostprovider = context.hostprovider
    upgrades_simple = 41
    upgrades_action = 20
    upgrades_total = upgrades_simple + upgrades_action

    assert await hostprovider.upgrades.all() == [await hostprovider.upgrades.get(name__eq="simple_provider")]

    new_bundle = await upload_hp_bundle_with_50_plus_upgrades(adcm_client=context.client, workdir=tmp_path)

    assert len(await hostprovider.upgrades.all()) == upgrades_total
    assert len(await hostprovider.upgrades.list()) == upgrades_total  # no paging
    assert len(await hostprovider.upgrades.filter(name__contains="simple")) == upgrades_simple
    assert len(await hostprovider.upgrades.filter(name__exclude=["simple-1", "action-2"])) == upgrades_total - 2
    assert (
        len(await hostprovider.upgrades.filter(display_name__iexclude=["sIMpLe-1", "AcTion-2"])) == upgrades_total - 2
    )
    assert len(await hostprovider.upgrades.filter(name__ne="simple-1")) == upgrades_total - 1
    assert len(await hostprovider.upgrades.filter(display_name__ine="sIMpLe-1")) == upgrades_total - 1
    assert await hostprovider.upgrades.get_or_none(display_name__eq="action-4") is not None

    async for upgrade in hostprovider.upgrades.iter(display_name__icontains="tIon"):
        assert upgrade.display_name.startswith("action-")
        assert (await upgrade.bundle).id == new_bundle.id
