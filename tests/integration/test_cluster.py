from pathlib import Path
from typing import Collection
import asyncio

from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.config import ConfigHistoryNode, ObjectConfig
from adcm_aio_client.core.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.core.mapping import ClusterMapping
from adcm_aio_client.core.objects.cm import Bundle, Cluster
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


async def get_ansible_forks(httpx_client: AsyncClient, cluster: Cluster) -> int:
    ansible_cfg_url = f"clusters/{cluster.id}/ansible-config/"
    response = await httpx_client.get(ansible_cfg_url)
    assert response.status_code == 200

    return response.json()["config"]["defaults"]["forks"]


async def update_cluster_name(httpx_client: AsyncClient, cluster: Cluster, new_name: str) -> None:
    cluster_url = f"clusters/{cluster.id}/"
    response = await httpx_client.patch(cluster_url, json={"name": new_name})
    assert response.status_code == 200


async def assert_cluster(cluster: Cluster, expected: dict, httpx_client: AsyncClient) -> None:
    cluster_url = f"clusters/{cluster.id}/"
    response = await httpx_client.get(cluster_url)
    assert response.status_code == 200

    response = response.json()
    for attr, value in expected.items():
        assert response[attr] == value

    await cluster.delete()
    response = await httpx_client.get(cluster_url)
    assert response.status_code == 404


def assert_clusters_collection(clusters: Collection[Cluster], expected_amount: int) -> None:
    assert all(isinstance(cluster, Cluster) for cluster in clusters)
    assert len({cluster.id for cluster in clusters}) == expected_amount
    assert len({id(cluster) for cluster in clusters}) == expected_amount


@pytest_asyncio.fixture()
async def complex_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def many_complex_clusters(adcm_client: ADCMClient, complex_cluster_bundle: Bundle) -> int:
    """
    Creates 51 clusters (2 pages, if response's page size is 50)
    with name pattern `Test-cluster-N` and one `Very special cluster`
    """

    num_similar_clusters = 50
    coros = (
        adcm_client.clusters.create(bundle=complex_cluster_bundle, name=f"Test-cluster-{i + 1}")
        for i in range(num_similar_clusters)
    )
    special_cluster_coro = adcm_client.clusters.create(bundle=complex_cluster_bundle, name="Very special cluster")
    await asyncio.gather(*coros, special_cluster_coro)

    return num_similar_clusters + 1


@pytest_asyncio.fixture()
async def simple_cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "simple_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def simple_cluster(adcm_client: ADCMClient, simple_cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(bundle=simple_cluster_bundle, name="Simple cluster")


async def test_cluster(
    adcm_client: ADCMClient,
    complex_cluster_bundle: Bundle,
    many_complex_clusters: int,
    simple_cluster_bundle: Bundle,
    simple_cluster: Cluster,  # for filtering by bundle
    httpx_client: AsyncClient,
) -> None:
    _ = simple_cluster
    num_clusters = many_complex_clusters + 1  # + simple_cluster

    await _test_cluster_create_delete_api(
        adcm_client=adcm_client, bundle=complex_cluster_bundle, httpx_client=httpx_client
    )

    await _test_clusters_node(
        adcm_client=adcm_client,
        complex_bundle=complex_cluster_bundle,
        num_clusters=num_clusters,
        simple_bundle=simple_cluster_bundle,
    )

    cluster = await adcm_client.clusters.get(name__eq="Very special cluster")
    await _test_cluster_object_api(httpx_client=httpx_client, cluster=cluster, cluster_bundle=complex_cluster_bundle)


async def _test_cluster_create_delete_api(adcm_client: ADCMClient, bundle: Bundle, httpx_client: AsyncClient) -> None:
    name = "Test-cluster"
    description = "des\ncription"
    cluster = await adcm_client.clusters.create(bundle=bundle, name=name, description=description)

    expected = {"id": cluster.id, "name": name, "description": description}
    await assert_cluster(cluster, expected, httpx_client)

    # without optional arguments
    name = "Another-test-cluster"
    cluster = await adcm_client.clusters.create(bundle=bundle, name=name)

    expected = {"id": cluster.id, "name": name, "description": ""}
    await assert_cluster(cluster, expected, httpx_client)


async def _test_clusters_node(
    adcm_client: ADCMClient, complex_bundle: Bundle, num_clusters: int, simple_bundle: Bundle
) -> None:
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await adcm_client.clusters.get(name__eq="Very special cluster"), Cluster)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.clusters.get(name__eq="Not so special cluster")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.clusters.get(name__in=["Test-cluster-1", "Test-cluster-2"])

    # get_or_none
    assert isinstance(await adcm_client.clusters.get_or_none(name__eq="Test-cluster-3"), Cluster)

    assert await adcm_client.clusters.get_or_none(name__eq="Not so special cluster") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.clusters.get_or_none(name__in=["Very special cluster", "Test-cluster-2"])

    # all
    all_clusters = await adcm_client.clusters.all()
    assert_clusters_collection(clusters=all_clusters, expected_amount=num_clusters)

    # list
    page_size = 50
    assert page_size < num_clusters, "check page_size or number of clusters"

    first_page_clusters = await adcm_client.clusters.list()
    assert_clusters_collection(clusters=first_page_clusters, expected_amount=page_size)

    # iter
    iter_clusters = set()
    async for cluster in adcm_client.clusters.iter():
        iter_clusters.add(cluster)
    assert_clusters_collection(clusters=iter_clusters, expected_amount=num_clusters)

    # filter
    # complex_bundle: "Test-cluster-N" - 50; "Very special cluster" - 1;
    # simple_bundle: "Simple cluster" - 1
    filters_data = {
        ("bundle__eq", simple_bundle): 1,
        ("bundle__in", (complex_bundle, simple_bundle)): num_clusters,
        ("bundle__ne", complex_bundle): 1,
        ("bundle__exclude", (simple_bundle, complex_bundle)): 0,
        ("name__eq", "Very special cluster"): 1,
        ("name__ieq", "VERY SPECIAL cluster"): 1,
        ("name__ne", "Simple cluster"): num_clusters - 1,
        ("name__ine", "SIMPLE CLUSTER"): num_clusters - 1,
        ("name__in", ("Test-cluster-1", "Test-cluster-2", "TEST-cluster-3", "Not a cluster")): 2,
        ("name__iin", ("TEST-cluster-1", "Test-CLUSTER-2", "SIMPLE CLUSTER")): 3,
        ("name__exclude", ("Test-cluster-1", "Test-cluster-2", "Not a cluster")): num_clusters - 2,
        ("name__iexclude", ("VERY special CLUSTER", "Not a cluster")): num_clusters - 1,
        ("name__contains", "special"): 1,
        ("name__icontains", "-ClUsTeR-"): num_clusters - 2,
        ("status__eq", "up"): 0,
        ("status__eq", "down"): num_clusters,
        ("status__in", ("down", "some status")): num_clusters,
        ("status__in", ("up", "some status")): 0,
        ("status__ne", "down"): 0,
        ("status__ne", "up"): num_clusters,
        ("status__exclude", ("excluded_status", "down")): 0,
        ("status__exclude", ("excluded_status", "up")): num_clusters,
        ("status__exclude", ("up", "down")): 0,
    }
    for filter_, expected in filters_data.items():
        filter_value = {filter_[0]: filter_[1]}
        clusters = await adcm_client.clusters.filter(**filter_value)
        assert len(clusters) == expected, f"Filter: {filter_value}"


async def _test_cluster_object_api(httpx_client: AsyncClient, cluster: Cluster, cluster_bundle: Bundle) -> None:
    assert isinstance(cluster.id, int)
    assert isinstance(cluster.name, str)
    assert isinstance(cluster.description, str)

    bundle = await cluster.bundle
    assert isinstance(bundle, Bundle)
    assert bundle.id == cluster_bundle.id

    assert isinstance(await cluster.get_status(), str)
    assert isinstance(await cluster.actions.all(), list)
    assert isinstance(await cluster.upgrades.all(), list)
    assert isinstance(await cluster.config_host_groups.all(), list)
    assert isinstance(await cluster.action_host_groups.all(), list)
    assert isinstance(await cluster.config, ObjectConfig)
    assert isinstance(cluster.config_history, ConfigHistoryNode)
    assert isinstance(await cluster.mapping, ClusterMapping)

    initial_ansible_forks = await get_ansible_forks(httpx_client, cluster)
    await cluster.set_ansible_forks(value=initial_ansible_forks + 5)
    assert await get_ansible_forks(httpx_client, cluster) == initial_ansible_forks + 5

    new_name = "New cluster name"
    await update_cluster_name(httpx_client, cluster, new_name)
    assert cluster.name != new_name
    await cluster.refresh()
    assert cluster.name == new_name
