from pathlib import Path
from typing import NamedTuple
import asyncio

import yaml
import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.config._objects import Parameter, ParameterGroup
from adcm_aio_client.core.errors import (
    ConfigNoParameterError,
    NoConfigInActionError,
    NoMappingInActionError,
    ResponseError,
)
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.mapping.refresh import apply_remote_changes
from adcm_aio_client.core.objects.cm import Bundle, HostProvider, Job
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

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
async def previous_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster_prev", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def hostprovider(adcm_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> HostProvider:
    return await adcm_client.hostproviders.create(simple_hostprovider_bundle, name="Simple HP")


@pytest.fixture()
def context(
    adcm_client: ADCMClient, previous_cluster_bundle: Bundle, complex_cluster_bundle: Bundle, hostprovider: HostProvider
) -> Context:
    return Context(
        client=adcm_client,
        old_bundle=previous_cluster_bundle,
        new_bundle=complex_cluster_bundle,
        hostprovider=hostprovider,
    )


async def test_upgrade_api(context: Context, tmp_path: Path) -> None:
    await _test_simple_upgrade(context)
    await _test_upgrade_with_config(context)
    await _test_upgrade_with_mapping(context)
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
    assert len(upgrades) == 2
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


async def _test_upgrade_with_mapping(context: Context) -> None:
    cluster = await context.client.clusters.create(context.old_bundle, "for mapping")
    await asyncio.gather(
        *(
            context.client.hosts.create(hostprovider=context.hostprovider, name=f"host-{i}", cluster=cluster)
            for i in range(3)
        )
    )
    service_1, *_ = await cluster.services.add(Filter(attr="name", op="eq", value="example_1"))
    service_2, *_ = await cluster.services.add(Filter(attr="name", op="eq", value="example_2"))

    # todo most likely bug
    #    upgrades = await cluster.upgrades.filter(
    # display_name__iexclude=["With action and config", "i am very simple, you know?"])
    #    assert len(upgrades) == 1, [u.display_name for u in upgrades]
    #    upgrade = upgrades[0]
    upgrade = await cluster.upgrades.get(name__eq="action_config_mapping")
    assert upgrade.name == "action_config_mapping"

    mapping = await upgrade.mapping
    assert mapping.all() == []

    assert len(await cluster.hosts.all()) == 3
    cluster_mapping = await cluster.mapping
    assert cluster_mapping.all() == []
    await cluster_mapping.add(
        component=await service_1.components.get(name__eq="second"),
        host=Filter(attr="name", op="contains", value="host"),
    )
    second_c_service_2 = await service_2.components.get(name__eq="second")
    await cluster_mapping.add(component=second_c_service_2, host=Filter(attr="name", op="ieq", value="HOsT-1"))
    assert len(cluster_mapping.all()) == 4
    await cluster_mapping.save()

    await upgrade.refresh()  # drop caches
    mapping = await upgrade.mapping
    assert len(mapping.all()) == 4
    await mapping.add(
        component=await service_1.components.get(display_name__eq="First Component"),
        host=await mapping.hosts.filter(name__in=["host-0", "host-2"]),
    )
    assert len(mapping.all()) == 6
    await mapping.remove(component=second_c_service_2, host=await mapping.hosts.get(name__eq="host-1"))
    assert len(mapping.all()) == 5

    config = await upgrade.config
    config["params", ParameterGroup]["pass", Parameter].set("notenough")

    # quite strange pick of response in here in ADCM, so generalized expected error
    with pytest.raises(ResponseError, match=".*config key.*is required"):
        await upgrade.run()

    config["string_field", Parameter].set("useless yet required")

    job = await upgrade.run()
    assert isinstance(job, Job)
    await job.wait(timeout=30, poll_interval=2)
    assert await job.get_status() == "success"

    await cluster_mapping.refresh(strategy=apply_remote_changes)
    assert len(cluster_mapping.all()) == 5


async def _test_upgrade_filtering(context: Context, tmp_path: Path) -> None:
    hostprovider = context.hostprovider
    upgrades_simple = 40
    upgrades_action = 20
    upgrades_total = upgrades_simple + upgrades_action

    assert await hostprovider.upgrades.all() == []

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
