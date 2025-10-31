import asyncio

from httpx import AsyncClient, Timeout
import pytest
import pytest_asyncio

from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import MultipleObjectsReturnedError, ObjectDoesNotExistError
from adcm_aio_client.objects import Bundle, Cluster, Host, HostProvider, Service
from adcm_aio_client.objects.rbac import group as group_module
from adcm_aio_client.objects.rbac import policy as policy_module
from adcm_aio_client.objects.rbac import role as role_module
from adcm_aio_client.objects.rbac._types import PolicyData, PolicyObject, PolicyRole

# pyright: reportAttributeAccessIssue=false


pytestmark = [pytest.mark.asyncio]


async def create_51_policy(httpx_client: AsyncClient, cluster: Cluster, group: group_module.LocalGroup) -> None:
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


async def get_polies_names(httpx_client: AsyncClient) -> list[str]:
    response = await httpx_client.get(url="rbac/policies/", params={"limit": 999})
    assert response.status_code == 200

    return [policy["name"] for policy in response.json()["results"]]


@pytest_asyncio.fixture()
async def group(adcm_client: ADCMClient, httpx_client: AsyncClient) -> group_module.LocalGroup:
    response = await httpx_client.post(url="rbac/groups/", data={"displayName": "Test group"})
    assert response.status_code == 201

    group = await adcm_client.groups.get(display_name__eq="Test group")
    assert isinstance(group, group_module.LocalGroup)

    return group


@pytest_asyncio.fixture()
async def new_group(adcm_client: ADCMClient, httpx_client: AsyncClient) -> group_module.LocalGroup:
    response = await httpx_client.post(url="rbac/groups/", data={"displayName": "New test group"})
    assert response.status_code == 201

    group = await adcm_client.groups.get(display_name__eq="Test group")
    assert isinstance(group, group_module.LocalGroup)

    return group


@pytest_asyncio.fixture()
async def simple_cluster(adcm_client: ADCMClient, simple_cluster_bundle: Bundle) -> Cluster:
    return await adcm_client.clusters.create(bundle=simple_cluster_bundle, name="Simple cluster")


@pytest_asyncio.fixture()
async def provider(adcm_client: ADCMClient, simple_hostprovider_bundle: Bundle) -> HostProvider:
    return await adcm_client.hostproviders.create(bundle=simple_hostprovider_bundle, name="Test HP")


# @pytest_asyncio.fixture()
# async def two_policies(
#     adcm_client: ADCMClient, httpx_client: AsyncClient, simple_cluster: Cluster, group: LocalGroup
# ) -> tuple[Policy, Policy]:
#     """Returns two policies: remote and created locally without saving"""
#     role = await adcm_client.roles.get(name__eq="Cluster Administrator")
#     assert isinstance(role, BuiltInRole)
#
#     data = {
#         "name": "cluster admin policy",
#         "role": {"id": role.id},
#         "objects": [{"id": simple_cluster.id, "type": "cluster"}],
#         "groups": [group.id],
#     }
#     response = await httpx_client.post(url="rbac/policies/", json=data, timeout=Timeout(15.0, read=None))
#     assert response.status_code == 201
#
#     policy = await adcm_client.policies.get(name__eq="cluster admin policy")
#
#     not_saved_policy = Policy(
#         client=adcm_client, name="cluster admin policy new", role=role, objects=[simple_cluster], groups=[group]
#     )
#
#     return policy, not_saved_policy
#


async def test_policy(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    # two_policies: tuple[policy_module.Policy, policy_module.Policy],
    simple_cluster: Cluster,
    group: group_module.LocalGroup,
    new_group: group_module.LocalGroup,
    provider: HostProvider,
) -> None:
    _test_fields_contract()
    await _test_policy_data_api(
        adcm_client=adcm_client, httpx_client=httpx_client, cluster=simple_cluster, group=group, new_group=new_group
    )
    await _test_policy_lazy_api(
        adcm_client=adcm_client, httpx_client=httpx_client, cluster=simple_cluster, provider=provider, group=group
    )
    await _test_policies_node(adcm_client=adcm_client, httpx_client=httpx_client, cluster=simple_cluster, group=group)


def _test_fields_contract() -> None:
    policydata = PolicyData.__annotations__
    policykwargs = policy_module._PolicyKwargs.__annotations__

    assert policydata.pop("id").__args__ == (int | None,)

    expected_fields = {"name", "role", "objects", "groups", "description"}
    assert set(policydata.keys()) == set(policykwargs.keys()) == expected_fields

    assert policydata.pop("role").__args__ == (PolicyRole | None,)
    assert policykwargs.pop("role").__args__ == (role_module.CustomRole | role_module.BuiltInRole,)

    assert policydata.pop("objects").__args__ == (list[PolicyObject] | None,)
    assert policykwargs.pop("objects").__args__ == (list[Cluster | Service | HostProvider | Host],)

    assert policydata.pop("groups").__args__ == (list[int] | None,)
    assert policykwargs.pop("groups").__args__ == (list[group_module.LocalGroup | group_module.LDAPGroup],)

    for field in policykwargs:
        kwarg_type = policykwargs[field].__args__[0]
        customroledata_type = policydata[field].__args__
        assert (kwarg_type | None,) == customroledata_type, f"{field=}, {kwarg_type=}, {customroledata_type=}"


async def _test_policy_data_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    cluster: Cluster,
    group: group_module.LocalGroup,
    new_group: group_module.LocalGroup,
) -> None:
    policy_name = "New policy"
    assert policy_name not in await get_polies_names(httpx_client)

    role = await adcm_client.roles.get(display_name__eq="Cluster Administrator")

    correct_data = {"name": policy_name, "role": role, "objects": [cluster], "groups": [group]}
    for arg_to_remove in correct_data:
        data = correct_data.copy()
        data.pop(arg_to_remove)
        with pytest.raises(
            ValueError,
            match=f'"name", "role", "objects" and "groups" are mandatory to create a {policy_module.Policy.__name__}',
        ):
            policy_module.new(**data)

    for wrong_type in ({"role": cluster}, {"objects": [role]}, {"groups": [policy_name]}):
        data = {**correct_data, **wrong_type}
        with pytest.raises(ValueError):
            policy_module.new(**data)

    policy = policy_module.new(**correct_data)
    description = "New description"
    assert isinstance(policy, policy_module.PolicyData)
    policy.description = description

    with pytest.raises(AttributeError):
        await policy.save()

    with pytest.raises(AttributeError):
        await policy.delete()

    policy = await adcm_client.policies.init(policy)

    assert isinstance(policy, policy_module.Policy)
    assert policy.name in await get_polies_names(httpx_client)

    assert isinstance(policy.id, int)
    assert policy.name == policy_name
    assert policy.description == description
    role_from_policy = await policy.role
    assert isinstance(role_from_policy, role_module.BuiltInRole)
    assert role_from_policy.id == role.id
    objects_from_policy = await policy.objects
    assert isinstance(objects_from_policy, list)
    assert len(objects_from_policy) == 1
    assert isinstance(objects_from_policy[0], Cluster)
    assert objects_from_policy[0].id == cluster.id
    groups_from_policy = await policy.groups
    assert isinstance(groups_from_policy, list)
    assert len(groups_from_policy) == 1
    assert isinstance(groups_from_policy[0], group_module.LocalGroup)
    assert groups_from_policy[0].id == group.id

    new_name = f"New {policy_name}"
    assert new_name not in await get_polies_names(httpx_client)

    wrong_data = ({"role": new_group}, {"objects": [role]}, {"groups": [cluster]})
    for data in wrong_data:
        with pytest.raises(ValueError):
            # pyright did not parse wrong_data and throws incorrect errors here
            policy.edit(**data)  # pyright: ignore[reportArgumentType]

    edited_policy = policy.edit(groups=[new_group])
    assert isinstance(edited_policy, policy_module.PolicyLazy)
    with pytest.raises(AttributeError):
        await edited_policy.delete()

    saved_policy = await edited_policy.save()
    assert isinstance(saved_policy, policy_module.Policy)
    assert saved_policy.name in await get_polies_names(httpx_client)
    groups_from_policy = await saved_policy.groups
    assert isinstance(groups_from_policy, list)
    assert len(groups_from_policy) == 1
    assert isinstance(groups_from_policy[0], group_module.LocalGroup)
    assert groups_from_policy[0].id == new_group.id

    await saved_policy.delete()
    assert saved_policy.name not in await get_polies_names(httpx_client)


async def _test_policy_lazy_api(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    cluster: Cluster,
    provider: HostProvider,
    group: group_module.LocalGroup,
) -> None:
    policy_name = "New_policy_from_node"
    assert policy_name not in await get_polies_names(httpx_client)

    role = await adcm_client.roles.get(display_name__eq="Cluster Administrator")
    assert isinstance(role, role_module.BuiltInRole)
    new_role = await adcm_client.roles.get(display_name__eq="Provider Administrator")
    assert isinstance(new_role, role_module.BuiltInRole)

    correct_data = {"name": policy_name, "role": role, "objects": [cluster], "groups": [group]}
    for arg_to_remove in correct_data:
        data = correct_data.copy()
        data.pop(arg_to_remove)
        with pytest.raises(
            ValueError,
            match=f'"name", "role", "objects" and "groups" are mandatory to create a {policy_module.Policy.__name__}',
        ):
            adcm_client.policies.new(**data)

    for wrong_type in ({"role": cluster}, {"objects": [1, 2]}, {"groups": [role]}):
        data = {**correct_data, **wrong_type}
        with pytest.raises(ValueError):
            adcm_client.policies.new(**data)

    policy = adcm_client.policies.new(**correct_data)

    assert isinstance(policy, policy_module.PolicyLazy)
    assert policy_name not in await get_polies_names(httpx_client)

    with pytest.raises(AttributeError):
        await policy.delete()

    description = "pol description"
    policy.description = description

    saved_policy = await policy.save()
    assert saved_policy.name in await get_polies_names(httpx_client)
    assert isinstance(saved_policy.id, int)
    assert saved_policy.name == policy_name
    assert saved_policy.description == description
    role_from_policy = await saved_policy.role
    assert isinstance(role_from_policy, role_module.BuiltInRole)
    assert role_from_policy.id == role.id
    objects_from_policy = await saved_policy.objects
    assert isinstance(objects_from_policy, list)
    assert len(objects_from_policy) == 1
    assert isinstance(objects_from_policy[0], Cluster)
    assert objects_from_policy[0].id == cluster.id
    groups_from_policy = await saved_policy.groups
    assert isinstance(groups_from_policy, list)
    assert len(groups_from_policy) == 1
    assert isinstance(groups_from_policy[0], group_module.LocalGroup)
    assert groups_from_policy[0].id == group.id

    new_name = f"New {policy_name}"
    edited_policy = saved_policy.edit(name=new_name, role=new_role, objects=[provider])
    assert isinstance(edited_policy, policy_module.PolicyLazy)
    with pytest.raises(AttributeError):
        await edited_policy.delete()

    saved_policy = await edited_policy.save()
    assert new_name in await get_polies_names(httpx_client)
    assert isinstance(saved_policy, policy_module.Policy)
    assert saved_policy.name == new_name
    role_from_policy = await saved_policy.role
    assert isinstance(role_from_policy, role_module.BuiltInRole)
    assert role_from_policy.id == new_role.id
    objects_from_policy = await saved_policy.objects
    assert isinstance(objects_from_policy, list)
    assert len(objects_from_policy) == 1
    assert isinstance(objects_from_policy[0], HostProvider)
    assert objects_from_policy[0].id == provider.id

    await saved_policy.delete()
    assert saved_policy.name not in await get_polies_names(httpx_client)


async def _test_policies_node(
    adcm_client: ADCMClient,
    httpx_client: AsyncClient,
    cluster: Cluster,
    group: group_module.LocalGroup,
) -> None:
    await create_51_policy(httpx_client, cluster, group)
    num_policies = await get_policies_count(httpx_client)
    no_objects_msg = "^No objects found with the given filter.$"
    multiple_objects_msg = "^More than one object found.$"

    # get
    assert isinstance(await adcm_client.policies.get(name__eq="Custom Policy 1"), policy_module.Policy)

    with pytest.raises(ObjectDoesNotExistError, match=no_objects_msg):
        await adcm_client.policies.get(name__eq="CustomPolicy")

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.policies.get(name__in=["Custom Policy 1", "Custom Policy 2"])

    # get_or_none
    assert isinstance(await adcm_client.policies.get_or_none(name__eq="Custom Policy 3"), policy_module.Policy)

    assert await adcm_client.policies.get_or_none(name__eq="NotAPolicy") is None

    with pytest.raises(MultipleObjectsReturnedError, match=multiple_objects_msg):
        await adcm_client.policies.get_or_none(name__in=["Custom Policy 4", "Custom Policy 5"])

    # all
    all_policies = await adcm_client.policies.all()
    assert all(isinstance(policy, policy_module.Policy) for policy in all_policies)
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
