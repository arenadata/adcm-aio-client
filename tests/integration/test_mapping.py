from collections.abc import Iterable
from copy import deepcopy
from itertools import chain
from pathlib import Path
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.mapping.refresh import apply_local_changes, apply_remote_changes
from adcm_aio_client.core.mapping.types import MappingPair
from adcm_aio_client.core.objects.cm import Bundle, Cluster, Host
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]

type FiveHosts = tuple[Host, Host, Host, Host, Host]


def build_name_mapping(*iterables: Iterable[MappingPair]) -> set[tuple[str, str, str]]:
    return {(c.service.name, c.name, h.name) for c, h in chain.from_iterable(iterables)}


@pytest_asyncio.fixture()
async def cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def hostprovider_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "simple_hostprovider", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="contains", value="example"))
    return cluster


@pytest_asyncio.fixture()
async def hosts(adcm_client: ADCMClient, hostprovider_bundle: Bundle) -> FiveHosts:
    hp = await adcm_client.hostproviders.create(bundle=hostprovider_bundle, name="Awesome HostProvider")
    coros = (adcm_client.hosts.create(hostprovider=hp, name=f"host-{i}") for i in range(5))
    await asyncio.gather(*coros)
    hosts = await adcm_client.hosts.all()
    return tuple(hosts)  # type: ignore[reportReturnType]


async def test_cluster_mapping(adcm_client: ADCMClient, cluster: Cluster, hosts: FiveHosts) -> None:
    mapping = await cluster.mapping

    assert len(mapping.all()) == 0
    assert len(await mapping.hosts.all()) == 0
    assert len(await mapping.components.all()) == 6

    await cluster.hosts.add(host=hosts)
    host_1, host_2, host_3, host_4, host_5 = await mapping.hosts.all()

    service_1 = await cluster.services.get(display_name__eq="First Example")
    service_2 = await cluster.services.get(name__eq="example_2")

    component_1_s1 = await service_1.components.get(name__eq="first")
    component_2_s2 = await service_2.components.get(display_name__in=["Second Component"])

    # local mapping editing

    await mapping.add(component=component_1_s1, host=host_1)
    assert len(tuple(mapping.iter())) == 1

    await mapping.add(component=(component_1_s1, component_2_s2), host=(host_1, host_3, host_4))
    assert len(mapping.all()) == 6

    await mapping.remove(component=component_2_s2, host=(host_2, host_3))
    assert len(mapping.all()) == 5

    await mapping.remove(component=(component_1_s1, component_2_s2), host=host_1)
    assert len(mapping.all()) == 3

    mapping.empty()
    assert mapping.all() == []

    # saving

    all_components = await mapping.components.all()

    await mapping.add(component=all_components, host=host_5)
    await mapping.add(component=component_1_s1, host=(host_2, host_3))
    await mapping.save()

    expected_mapping = build_name_mapping(
        ((c, host_5) for c in all_components), ((component_1_s1, h) for h in (host_2, host_3))
    )
    actual_mapping = build_name_mapping(mapping.iter())
    assert actual_mapping == expected_mapping

    # refreshing

    cluster_alt = await adcm_client.clusters.get(name__eq=cluster.name)
    mapping_alt = await cluster_alt.mapping

    assert build_name_mapping(mapping.iter()) == build_name_mapping(mapping_alt.iter())

    component_3_s2 = await service_2.components.get(name__eq="third_one")
    components_except_3_s2 = tuple(c for c in all_components if c.id != component_3_s2.id)

    await mapping_alt.remove(component_1_s1, host_3)
    await mapping_alt.add(component_3_s2, (host_2, host_4))

    await mapping.add((component_1_s1, component_3_s2), host_1)
    await mapping.remove(component_3_s2, host_5)

    await mapping_alt.save()

    pre_refresh_mapping = deepcopy(mapping)
    await mapping.refresh(strategy=apply_remote_changes)

    expected_mapping = build_name_mapping(
        ((c, host_5) for c in components_except_3_s2),
        ((component_1_s1, h) for h in (host_1, host_2)),
        ((component_3_s2, h) for h in (host_1, host_2, host_4)),
    )
    actual_mapping = build_name_mapping(mapping.iter())
    assert actual_mapping == expected_mapping

    mapping = pre_refresh_mapping
    await mapping.refresh(strategy=apply_local_changes)

    expected_mapping = (
        # base is remote, but with local changes
        build_name_mapping(mapping_alt.iter())
        # add what's added locally
        | build_name_mapping(((component_1_s1, host_1), (component_3_s2, host_1)))
        # remove what's removed locally
        - build_name_mapping(((component_3_s2, host_5),))
    )
    actual_mapping = build_name_mapping(mapping.iter())
    assert actual_mapping == expected_mapping


# todo add case with removing with filter too
#    await mapping.add(
#        component=await mapping.components.filter(display_name__icontains="different"),
#        host=Filter(attr="name", op="in", value=(host_2.name, host_5.name)),
#    )
#    assert len(mapping.all()) == 10
