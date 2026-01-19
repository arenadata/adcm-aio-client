from typing import cast
import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import (
    BuiltInRole,
    Bundle,
    Cluster,
    CustomRole,
    LocalGroup,
    Permission,
    Policy,
)

pytestmark = [pytest.mark.asyncio]


async def create_51_policy(httpx_client: AsyncClient, cluster: Cluster, group: LocalGroup) -> None:
    response = await httpx_client.get(url="rbac/roles/", params={"name__eq": "Cluster Administrator"})
    assert response.status_code == 200
    role_id = response.json()["results"][0]["id"]

    requests = []
    for i in range(1, 52, 1):
        data = {
            "name": f"Custom Policy {i}",
            "role": {"id": role_id},
            "objects": [{"id": cluster.id, "type": "cluster"}],
            "groups": [group.id],
        }
        requests.append(httpx_client.post(url="rbac/policies/", json=data, timeout=Timeout(15.0, read=None)))

    results = await asyncio.gather(*requests, return_exceptions=False)
    assert all(response.status_code == 201 for response in results)


async def get_policies_count(httpx_client: AsyncClient) -> int:
    response = await httpx_client.get(url="rbac/policies/", params={"limit": 1})
    assert response.status_code == 200

    return int(response.json()["count"])


async def assert_policy(policy: Policy, expected: dict, httpx_client: AsyncClient) -> None:
    response = await httpx_client.get(f"rbac/policies/{policy.id}/")
    assert response.status_code == 200

    response = response.json()
    for attr, value in expected.items():
        assert response[attr] == value


@pytest_asyncio.fixture()
async def group(adcm_client: ADCMClient, httpx_client: AsyncClient) -> LocalGroup:
    response = await httpx_client.post(url="rbac/groups/", data={"displayName": "Test group"})
    assert response.status_code == 201

    group = await adcm_client.groups.get(display_name__eq="Test group")
    assert isinstance(group, LocalGroup)

    return group


@pytest_asyncio.fixture()
async def simple_cluster(adcm_client: ADCMClient, simple_cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(bundle=simple_cluster_bundle, name="Simple cluster")


async def test_policy(
    adcm_client: ADCMClient, httpx_client: AsyncClient, simple_cluster: Cluster, group: LocalGroup
) -> None:
    await _test_create_delete_api(
        adcm_client=adcm_client, httpx_client=httpx_client, group=group, cluster=simple_cluster
    )
    await _test_policies_node(adcm_client=adcm_client, httpx_client=httpx_client, cluster=simple_cluster, group=group)


async def _test_create_delete_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    group: LocalGroup,
    cluster: Cluster,
) -> None:
    name = "Test policy"
    role = cast(BuiltInRole, await adcm_client.roles.get(name__eq="Cluster Administrator"))
    policy = await adcm_client.policies.create(
        name=name, role=role, objects=[cluster], groups=[group], description="dsc"
    )

    assert isinstance(policy, Policy)
    expected = {
        "id": policy.id,
        "name": name,
        "description": "dsc",
        "isBuiltIn": False,
        "objects": [{"id": cluster.id, "type": "cluster", "name": cluster.name, "displayName": cluster.name}],
        "groups": [{"id": group.id, "name": f"{group.display_name} [local]", "displayName": group.display_name}],
        "role": {"id": role.id, "name": role.name, "displayName": role.display_name},
    }
    await assert_policy(policy, expected, httpx_client)

    await policy.delete()
    response = await httpx_client.get(f"rbac/policies/{policy.id}/")
    assert response.status_code == 404

    # without object
    role_name, policy_name = "My role", "My policy"
    permissions = cast(
        list[Permission],
        await adcm_client.permissions.filter(name__iin=["view any object configuration", "view any object import"]),
    )
    custom_role = await adcm_client.roles.create(display_name=role_name, permissions=permissions)
    assert isinstance(custom_role, CustomRole)
    policy_without_objects = await adcm_client.policies.create(policy_name, role=custom_role, groups=[group])
    assert isinstance(policy_without_objects, Policy)

    expected_no_objects = {
        "id": policy_without_objects.id,
        "name": policy_name,
        "description": "",
        "isBuiltIn": False,
        "objects": [],
        "groups": [{"id": group.id, "name": f"{group.display_name} [local]", "displayName": group.display_name}],
        "role": {"id": custom_role.id, "name": custom_role.name, "displayName": custom_role.display_name},
    }
    await assert_policy(policy_without_objects, expected_no_objects, httpx_client)

    await policy_without_objects.delete()
    response = await httpx_client.get(f"rbac/policies/{policy_without_objects.id}/")
    assert response.status_code == 404


async def _test_policies_node(
    adcm_client: ADCMClient, httpx_client: AsyncClient, cluster: Cluster, group: LocalGroup
) -> None:
    await create_51_policy(httpx_client=httpx_client, cluster=cluster, group=group)
    num_policies = await get_policies_count(httpx_client)
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await adcm_client.policies.get(name__eq="Custom Policy 1"), Policy)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.policies.get(name__eq="CustomPolicy")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.policies.get(name__in=["Custom Policy 1", "Custom Policy 2"])

    # get_or_none
    assert isinstance(await adcm_client.policies.get_or_none(name__eq="Custom Policy 3"), Policy)

    assert await adcm_client.policies.get_or_none(name__eq="NotAPolicy") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.policies.get_or_none(name__in=["Custom Policy 4", "Custom Policy 5"])

    # all
    all_policies = await adcm_client.policies.all()
    assert all(isinstance(policy, Policy) for policy in all_policies)
    assert len({policy.id for policy in all_policies}) == num_policies
    assert len({id(policy) for policy in all_policies}) == num_policies

    # list
    page_size = 50
    assert page_size < num_policies, "check page_size or number of policies"

    first_page_policies = await adcm_client.policies.list()
    assert len({policy.id for policy in first_page_policies}) == page_size
    assert len({id(policy) for policy in first_page_policies}) == page_size

    # iter
    iter_policies = []
    async for policy in adcm_client.policies.iter():
        iter_policies.append(policy)
    assert len(iter_policies) == num_policies
    assert len({policy.id for policy in iter_policies}) == num_policies
    assert len({id(policy) for policy in iter_policies}) == num_policies

    # filter
    filters_data = (
        ("name__eq", ("Custom Policy 6", 1)),
        ("name__ne", ("Custom Policy 7", num_policies - 1)),
        ("name__in", (["Custom Policy 8", "Custom Policy 9", "Custom Policy 10"], 3)),
        (
            "name__exclude",
            (["Custom Policy 11", "Custom Policy 12", "Custom Policy 13"], num_policies - 3),
        ),
        ("name__ieq", ("CUSTOM Policy 14", 1)),
        ("name__ine", ("Custom POLICY 15", num_policies - 1)),
        ("name__iin", (["Custom POLICY 16", "CUSTOM Policy 17", "custOM POLicy 18"], 3)),
        (
            "name__iexclude",
            (["CUSTOM Policy 19", "Custom POLICY 20", "CuStOm PoLiCy 21"], num_policies - 3),
        ),
        ("name__contains", ("CustoM", 0)),
        ("name__icontains", ("CustoM", 51)),
    )

    for filter_key, (filter_value, expected) in filters_data:
        filter_dict = {filter_key: filter_value}
        role = await adcm_client.policies.filter(**filter_dict)
        assert len(role) == expected, f"Policy filter: {filter_dict}"
