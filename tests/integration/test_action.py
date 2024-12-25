from pathlib import Path
from typing import Iterable, NamedTuple
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
from adcm_aio_client.core.objects._common import WithActions
from adcm_aio_client.core.objects.cm import Bundle, Host, HostProvider, Job
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]

async def create_host_with_50_plus_actions(adcm_client: ADCMClient, workdir: Path) -> Host:
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
    bundle = await adcm_client.bundles.create(source=bundle_path)

    hostprovider = await adcm_client.hostproviders.create(bundle, "hpwithactions")

    name = "lots-of-actions.com"
    await adcm_client.hosts.create(hostprovider, name)

    return await adcm_client.hosts.get(name__eq=name)

class Context(NamedTuple):
    client: ADCMClient
    objects: tuple[WithActions, ...]
    tempdir: Path

@pytest_asyncio.fixture()
async def objects_with_actions(
        adcm_client: ADCMClient,
        complex_cluster_bundle: Bundle,
        complex_hostprovider_bundle: Bundle) -> tuple[WithActions, ...]:
    cluster = await adcm_client.clusters.create(complex_cluster_bundle, "target me")
    service, *_ = await cluster.services.add(Filter(attr="name", op="eq",
                                                    value="with_actions"))
    component = await service.components.get(name__eq="c1")

    action_group = await component.action_host_groups.create(name="ahg for c1")

    hostprovider = await adcm_client.hostproviders.create(complex_hostprovider_bundle, "i host")
    host = await adcm_client.hosts.create(hostprovider, "host-example")

    return (cluster, service, component, action_group, hostprovider, host)

@pytest.fixture()
def context(adcm_client: ADCMClient,
            objects_with_actions: tuple[WithActions, ...],
            tmp_path: Path) -> Context:
    return Context(
            client=adcm_client,
            objects=objects_with_actions,
            tempdir=tmp_path)

async def test_action_api(context: Context) -> None:
    await _test_action_with_config(context)
    await _test_action_with_mapping(context)
    await _test_action_filtering(context)

async def _test_action_with_config(context: Context) -> None:
    ...
async def _test_action_with_mapping(context: Context) -> None:
    ...
async def _test_action_filtering(context: Context) -> None:
    ...

