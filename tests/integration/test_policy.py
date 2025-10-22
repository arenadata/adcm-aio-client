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
    HostProvider,
    LocalGroup,
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


@pytest_asyncio.fixture()
async def group(adcm_client: ADCMClient, httpx_client: AsyncClient) -> LocalGroup:
    response = await httpx_client.post(url="rbac/groups/", data={"displayName": "Test group"})
    assert response.status_code == 201

    group = await adcm_client.groups.get(display_name__eq="Test group")
    assert isinstance(group, LocalGroup)

    return group


@pytest_asyncio.fixture()
async def new_group(adcm_client: ADCMClient, httpx_client: AsyncClient) -> LocalGroup:
    response = await httpx_client.post(url="rbac/groups/", data={"displayName": "New test group"})
    assert response.status_code == 201

    group = await adcm_client.groups.get(display_name__eq="Test group")
    assert isinstance(group, LocalGroup)

    return group


@pytest_asyncio.fixture()
async def simple_cluster(adcm_client: ADCMClient, simple_cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(bundle=simple_cluster_bundle, name="Simple cluster")


@pytest_asyncio.fixture()
async def provider(adcm_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> HostProvider:
    return await adcm_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Test HP")


@pytest_asyncio.fixture()
async def two_policies(
    adcm_client: ADCMClient, httpx_client: AsyncClient, simple_cluster: Cluster, group: LocalGroup
) -> tuple[Policy, Policy]:
    """Returns two policies: remote and created locally without saving"""
    role = await adcm_client.roles.get(name__eq="Cluster Administrator")
    assert isinstance(role, BuiltInRole)

    data = {
        "name": "cluster admin policy",
        "role": {"id": role.id},
        "objects": [{"id": simple_cluster.id, "type": "cluster"}],
        "groups": [group.id],
    }
    response = await httpx_client.post(url="rbac/policies/", json=data, timeout=Timeout(15.0, read=None))
    assert response.status_code == 201

    policy = await adcm_client.policies.get(name__eq="cluster admin policy")

    not_saved_policy = Policy(
        client=adcm_client, name="cluster admin policy new", role=role, objects=[simple_cluster], groups=[group]
    )

    return policy, not_saved_policy


async def test_role(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    two_policies: tuple[Policy, Policy],
    simple_cluster: Cluster,
    group: LocalGroup,
    new_group: LocalGroup,
    provider: HostProvider,
) -> None:
    await create_51_policy(httpx_client=httpx_client, cluster=simple_cluster, group=group)
    await _test_object_api(
        adcm_client=adcm_client,
        two_policies=two_policies,
        group=group,
        new_group=new_group,
        object_=simple_cluster,
        new_object=provider,
    )
    await _test_policies_node(adcm_client, httpx_client)


async def _test_object_api(
    adcm_client: ADCMClient,
    two_policies: tuple[Policy, Policy],
    group: LocalGroup,
    new_group: LocalGroup,
    object_: Cluster,
    new_object: HostProvider,
) -> None:
    policy, not_saved_policy = two_policies
    assert isinstance(policy.id, int)
    assert not_saved_policy.id is None

    await policy.delete()
    with pytest.raises(ObjectDoesNotExistError):
        await adcm_client.policies.get(name__eq=policy.name)

    with pytest.raises(ObjectDoesNotExistError):
        await adcm_client.policies.get(name__eq=not_saved_policy.name)

    await not_saved_policy.save()
    assert isinstance(not_saved_policy.id, int)

    policy = await adcm_client.policies.get(name__eq=not_saved_policy.name)
    assert isinstance(policy, Policy)
    assert isinstance(policy.id, int)
    assert policy.name == "cluster admin policy new"
    assert policy.description == ""
    assert await policy.objects == [object_]
    assert await policy.role == await adcm_client.roles.get(name__eq="Cluster Administrator")
    assert await policy.groups == [group]

    new_role = await adcm_client.roles.get(name__eq="Provider Administrator")
    assert isinstance(new_role, BuiltInRole)

    policy.name = "new policy name"
    policy.description = "new policy description"
    policy.objects = [new_object]
    policy.role = new_role
    policy.groups = [new_group]
    assert policy._manually_set == {"name", "description", "objects", "role", "groups"}

    await policy.save()
    await policy.refresh()
    assert policy._manually_set == set()

    assert policy.name == "new policy name" == policy._data["name"]
    assert policy.description == "new policy description" == policy._data["description"]
    assert await policy.objects == [new_object]
    assert policy._data["objects"] == [
        {"id": new_object.id, "type": "provider", "name": new_object.name, "displayName": new_object.name}
    ]
    assert await policy.role == new_role
    assert policy._data["role"] == {"id": new_role.id, "name": new_role.name, "displayName": new_role.display_name}
    assert await policy.groups == [new_group]
    assert policy._data["groups"] == [
        {"id": new_group.id, "name": f"{new_group.display_name} [local]", "displayName": new_group.display_name}
    ]

    wrong_args = (
        {"name": "name", "role": new_role, "objects": [new_object], "groups": [new_group]},
        {"client": adcm_client, "role": new_role, "objects": [new_object], "groups": [new_group]},
        {"client": adcm_client, "name": "name", "objects": [new_object], "groups": [new_group]},
        {"client": adcm_client, "name": "name", "role": new_role, "groups": [new_group]},
        {"client": adcm_client, "name": "name", "role": new_role, "objects": [new_object]},
    )
    for args in wrong_args:
        with pytest.raises(RuntimeError):
            Policy(**args)


async def _test_policies_node(adcm_client: ADCMClient, httpx_client: AsyncClient) -> None:
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
