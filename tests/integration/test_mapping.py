from collections.abc import Iterable
from itertools import chain
import asyncio

import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.mapping import apply_local_changes, apply_remote_changes
from adcm_aio_client.mapping._types import MappingPair
from adcm_aio_client.objects import Bundle, Cluster, Host

pytestmark = [pytest.mark.asyncio]

type FiveHosts = tuple[Host, Host, Host, Host, Host]


def build_name_mapping(*iterables: Iterable[MappingPair]) -> set[tuple[str, str, str]]:
    return {(c.service.name, c.name, h.name) for c, h in chain.from_iterable(iterables)}


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, complex_cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=complex_cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="contains", value="example"))
    return cluster


@pytest_asyncio.fixture()
async def hosts(adcm_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> FiveHosts:
    hp = await adcm_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Awesome HostProvider")
    coros = (adcm_client.hosts.create(hostprovider=hp, name=f"host-{i+1}") for i in range(5))
    await asyncio.gather(*coros)
    hosts = await adcm_client.hosts.all()
    return tuple(hosts)  # type: ignore[reportReturnType]


async def test_cluster_mapping(adcm_client: ADCMClient, cluster: Cluster, hosts: FiveHosts) -> None:
    mapping = await cluster.mapping

    assert len(mapping.all()) == 0
    assert len(await mapping.hosts.all()) == 0
    assert len(await mapping.components.all()) == 6

    await cluster.hosts.add(host=hosts)
    h1, h2, h3, h4, h5 = await mapping.hosts.all()

    service_1 = await cluster.services.get(display_name__eq="First Example")
    service_2 = await cluster.services.get(name__eq="example_2")

    c1 = await service_1.components.get(name__eq="first")
    c2 = await service_2.components.get(display_name__in=["Second Component"])

    # local mapping editing

    await mapping.add(component=c1, host=h1)
    assert len(tuple(mapping.iter())) == 1

    await mapping.add(component=(c1, c2), host=(h1, h3, h4))
    assert len(mapping.all()) == 6

    await mapping.remove(component=c2, host=(h2, h3))
    assert len(mapping.all()) == 5

    await mapping.remove(component=(c1, c2), host=h1)
    assert len(mapping.all()) == 3

    await mapping.add(
        component=await mapping.components.filter(display_name__icontains="different"),
        host=Filter(attr="name", op="in", value=(h2.name, h5.name)),
    )
    assert len(mapping.all()) == 7

    await mapping.remove(
        component=await mapping.components.filter(display_name__icontains="different"),
        host=Filter(attr="name", op="in", value=(h2.name, h5.name)),
    )
    assert len(mapping.all()) == 3

    mapping.empty()
    assert mapping.all() == []

    # saving

    all_components = await mapping.components.all()

    await mapping.add(component=all_components, host=h5)
    await mapping.add(component=c1, host=(h2, h3))
    await mapping.save()

    expected_mapping = build_name_mapping(((c, h5) for c in all_components), ((c1, h) for h in (h2, h3)))
    actual_mapping = build_name_mapping(mapping.iter())
    assert actual_mapping == expected_mapping

    # refreshing

    cluster_alt = await adcm_client.clusters.get(name__eq=cluster.name)
    mapping_alt = await cluster_alt.mapping

    assert build_name_mapping(mapping.iter()) == build_name_mapping(mapping_alt.iter())

    c3 = await service_2.components.get(name__eq="third_one")

    await mapping_alt.remove(c1, h3)
    await mapping_alt.add(c3, (h2, h4))

    await mapping.add((c1, c3), h1)
    await mapping.remove(c3, h5)

    await mapping_alt.save()

    await mapping.refresh(strategy=apply_remote_changes)

    expected_mapping = build_name_mapping(
        ((c, h5) for c in all_components),
        ((c1, h) for h in (h1, h2)),
        ((c3, h) for h in (h1, h2, h4)),
    )
    actual_mapping = build_name_mapping(mapping.iter())
    assert actual_mapping == expected_mapping

    # drop cached mapping and apply the same local changes
    await cluster.refresh()
    mapping = await cluster.mapping

    await mapping.add((c1, c3), h1)
    await mapping.remove(c3, h5)

    await mapping.refresh(strategy=apply_local_changes)

    expected_mapping = (
        # base is remote, but with local changes
        build_name_mapping(mapping_alt.iter())
        # remove what's removed locally
        - build_name_mapping(((c3, h5),))
        # add what's added locally
        | build_name_mapping(((c1, h1), (c3, h1)))
    )
    actual_mapping = build_name_mapping(mapping.iter())
    assert actual_mapping == expected_mapping


async def test_refresh_strategies(cluster: Cluster, hosts: FiveHosts) -> None:
    service_1 = await cluster.services.get(display_name__eq="First Example")
    c1, c2, c3 = await service_1.components.all()
    h1, h2, *_ = hosts
    await cluster.hosts.add((h1, h2))

    mapping = await cluster.mapping
    await mapping.add(c1, h1)
    await mapping.add(c1, h2)
    await mapping.save()

    mapping_1 = await (await cluster.refresh()).mapping
    mapping_2 = await (await cluster.refresh()).mapping

    # changes in remote, and same changes for "parallel user" mappings
    await mapping.remove(c1, h2)
    await mapping.add(c3, h1)
    await mapping.save()

    for mapping_ in (mapping_1, mapping_2):
        await mapping_.remove(c1, h1)
        await mapping_.add(c2, h1)

    # local
    expected = build_name_mapping(((c1, h2), (c2, h1), (c3, h1)))
    await mapping_1.refresh(strategy=apply_local_changes)
    assert build_name_mapping(mapping_1.all()) == expected

    # remote
    expected = build_name_mapping(((c1, h1), (c2, h1), (c3, h1)))
    await mapping_2.refresh(strategy=apply_remote_changes)
    assert build_name_mapping(mapping_2.all()) == expected
