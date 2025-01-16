from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import yaml
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import Parameter
from adcm_aio_client.config._objects import ActionConfig
from adcm_aio_client.errors import (
    NoConfigInActionError,
    NoMappingInActionError,
    UnknownError,
)
from adcm_aio_client.host_groups._action_group import ActionHostGroup
from adcm_aio_client.mapping._objects import ActionMapping
from adcm_aio_client.objects import Bundle, Cluster, Component, Host, HostProvider, Job, Service
from adcm_aio_client.objects._common import WithActions
from tests.integration.bundle import pack_bundle

pytestmark = [pytest.mark.asyncio]


async def create_host_with_50_plus_actions(adcm_client: ADCMClient, workdir: Path) -> Host:
    bundle = [
        {
            "type": "provider",
            "name": "simple_provider",
            "version": 6,
        },
        {
            "type": "host",
            "name": "simple_host",
            "version": 2,
            "actions": {
                f"action_{i}": {
                    "display_name": f"Action {i}",
                    "type": "job",
                    "script_type": "ansible",
                    "script": "some.yaml",
                    "masking": {},
                }
                for i in range(60)
            },
        },
    ]

    bundle_dir = workdir / "hp_bundle_many_actions"
    config_file = bundle_dir / "config.yaml"

    bundle_dir.mkdir(parents=True)
    with config_file.open(mode="w", encoding="utf-8") as f:
        yaml.safe_dump(bundle, f)

    bundle_path = pack_bundle(from_dir=bundle_dir, to=workdir)
    bundle = await adcm_client.bundles.create(source=bundle_path)

    hostprovider = await adcm_client.hostproviders.create(bundle, "hpwithactions")

    name = "lots-of-actions.com"
    await adcm_client.hosts.create(hostprovider, name)

    return await adcm_client.hosts.get(name__eq=name)


def instance_of(*types: type) -> Callable[[Any], bool]:
    return lambda x: isinstance(x, types)


class Context(NamedTuple):
    client: ADCMClient
    objects: tuple[WithActions, ...]
    tempdir: Path


@pytest_asyncio.fixture()
async def objects_with_actions(
    adcm_client: ADCMClient, complex_cluster_bundle: Bundle, complex_hostprovider_bundle: Bundle
) -> tuple[WithActions, ...]:
    cluster = await adcm_client.clusters.create(complex_cluster_bundle, "target me")
    service, *_ = await cluster.services.add(Filter(attr="name", op="eq", value="with_actions"))
    component = await service.components.get(name__eq="c1")

    action_group = await component.action_host_groups.create(name="ahg for c1")

    hostprovider = await adcm_client.hostproviders.create(complex_hostprovider_bundle, "i host")
    host = await adcm_client.hosts.create(hostprovider, "host-example")

    return (cluster, service, component, action_group, hostprovider, host)


@pytest.fixture()
def context(adcm_client: ADCMClient, objects_with_actions: tuple[WithActions, ...], tmp_path: Path) -> Context:
    return Context(client=adcm_client, objects=objects_with_actions, tempdir=tmp_path)


async def test_action_api(context: Context) -> None:
    await _test_cluster_related_action_properties(context)
    await _test_host_related_action_properties(context)
    await _test_action_filtering(context)


async def _test_cluster_related_action_properties(context: Context) -> None:
    is_of_cluster_hierarchy = instance_of(Cluster, Service, Component, ActionHostGroup)
    for object_ in filter(is_of_cluster_hierarchy, context.objects):
        with_config = await object_.actions.get(name__eq="with_config")
        with_mapping = await object_.actions.get_or_none(display_name__in=["I will change the cluster"])
        assert with_mapping is not None
        with_both = await anext(object_.actions.iter(display_name__icontains="jOa"), None)
        assert with_both is not None

        actions = (with_config, with_mapping, with_both)

        for action in actions:
            assert isinstance(action.id, int)
            assert action.blocking is True
            assert action.verbose is False

        expected_names = {"with_config", "with_mapping", "with_config_and_mapping"}
        actual_names = {a.name for a in actions}
        assert actual_names == expected_names

        expected_display_names = {"Configurable one", "I will change the cluster", "JOAT"}
        actual_display_names = {a.display_name for a in actions}
        assert actual_display_names == expected_display_names

        with pytest.raises(NoMappingInActionError):
            await with_config.mapping

        with pytest.raises(NoConfigInActionError):
            await with_mapping.config

        assert isinstance(await with_mapping.mapping, ActionMapping)
        assert isinstance(await with_both.mapping, ActionMapping)
        assert isinstance(await with_both.config, ActionConfig)
        assert isinstance(await with_config.config, ActionConfig)


async def _test_host_related_action_properties(context: Context) -> None:
    is_of_host_hierarchy = instance_of(Host, HostProvider)
    for object_ in filter(is_of_host_hierarchy, context.objects):
        action = await object_.actions.get(name__ieq="wiTh_coNfig")

        assert isinstance(action.id, int)
        assert action.blocking is True
        assert action.verbose is False
        assert action.name == "with_config"
        assert action.display_name == "Configurable one"

        with pytest.raises(NoMappingInActionError):
            await action.mapping

        action_config = await action.config
        assert isinstance(action_config, ActionConfig)

        action.verbose = True
        action.blocking = False
        assert action.blocking is False
        assert action.verbose is True

        config = await action.config
        # check caching
        assert config is action_config

        # quite strange pick of response in here in ADCM, so generalized expected error
        with pytest.raises(UnknownError, match=".*config key.*is required"):
            await action.run()

        config["string_field", Parameter].set("sample")

        job = await action.run()
        assert isinstance(job, Job)


async def _test_action_filtering(context: Context) -> None:
    host = await create_host_with_50_plus_actions(adcm_client=context.client, workdir=context.tempdir)

    total_actions = len(await host.actions.all())

    result = await host.actions.list()
    assert total_actions > 50
    assert total_actions == len(result)

    cases = (
        # name
        ("name__eq", "action_1", 1),
        ("name__ieq", "aCtion_1", 1),
        ("name__ne", "action_1", total_actions - 1),
        ("name__ine", "aCtion_1", total_actions - 1),
        ("name__contains", "1", 15),
        ("name__icontains", "N_1", 11),
        ("name__in", ["action_1", "action_2"], 2),
        ("name__iin", ["actioN_1", "actIon_2"], 2),
        ("name__exclude", ["action_1", "action_2"], total_actions - 2),
        ("name__iexclude", ["actioN_1", "actIon_2"], total_actions - 2),
        # display name
        ("display_name__eq", "Action 1", 1),
        ("display_name__ieq", "aCtion 1", 1),
        ("display_name__ne", "Action 1", total_actions - 1),
        ("display_name__ine", "aCtion 1", total_actions - 1),
        ("display_name__contains", "1", 15),
        ("display_name__icontains", "N 1", 11),
        ("display_name__in", ["Action 1", "Action 2"], 2),
        ("display_name__iin", ["actioN 1", "actIon 2"], 2),
        ("display_name__exclude", ["Action 1", "Action 2"], total_actions - 2),
        ("display_name__iexclude", ["actioN 1", "actIon 2"], total_actions - 2),
    )

    for filter_name, filter_value, expected_amount in cases:
        filter_ = {filter_name: filter_value}
        result = await host.actions.filter(**filter_)
        actual_amount = len(result)
        assert (
            actual_amount == expected_amount
        ), f"Incorrect amount of actions for {filter_=}\nExpected: {expected_amount}\nActual: {actual_amount}\n{result}"
