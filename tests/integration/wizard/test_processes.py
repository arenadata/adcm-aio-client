from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.actions._objects import ConfigurationUnit, MappingUnit, OperationUnit
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import Parameter
from adcm_aio_client.errors import UnitExecutionError, WaitTimeoutError
from adcm_aio_client.mapping._types import MappingPair
from adcm_aio_client.objects import Action, Bundle, Cluster, Component, Flow, Host

pytestmark = [pytest.mark.asyncio]

OPERATION_STEPS_COUNT = 3
SUCCESS_TIMEOUT = 10
FAIL_TIMEOUT = 1


@pytest_asyncio.fixture()
async def wizard_cluster(adcm_client: ADCMClient, wizard_cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=wizard_cluster_bundle, name="Wizard Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="service_1"))
    return cluster


async def _test_action_flow_success(action: Action) -> None:
    flow = await action.pre_process.init()
    units = flow.units
    assert len(units) == OPERATION_STEPS_COUNT
    unit1, unit2, unit3 = units
    # check for pyright
    assert isinstance(unit1, OperationUnit)
    assert isinstance(unit2, OperationUnit)
    assert isinstance(unit3, OperationUnit)
    # check the data definition for steps
    assert unit1.name == "stage1_step1"
    assert unit1.stage == "First stage"
    assert unit3.stage == "Second stage"
    # check execute and skip units
    await unit1.execute()
    assert await unit2.skip() is True
    await unit3.execute()
    assert await flow.complete() is True
    # check states
    assert await unit1.get_state() == "completed"
    assert await unit2.get_state() == "skipped"
    assert await unit3.get_state() == "completed"
    assert await flow.get_state() == "completed"


async def _test_action_flow_fail_context_manager(action: Action) -> None:
    # All steps must be completed for a successful complete of a process
    flow = await action.pre_process.init()
    assert await flow.complete() is False


async def _test_action_flow_fail_timeout(adcm_client: ADCMClient, cluster: Cluster, action: Action) -> None:
    flow = await action.pre_process.init()
    unit = flow.units[0]
    assert isinstance(unit, OperationUnit)

    with pytest.raises(WaitTimeoutError):
        await unit.execute(timeout=FAIL_TIMEOUT)

    # get the last task and wait for complete for next tests
    jobs = await adcm_client.jobs.filter(object=cluster, name__eq=action.name)
    job = max(jobs, key=lambda job: job.id)
    await job.wait(timeout=SUCCESS_TIMEOUT, poll_interval=1)


async def _test_action_flow_fail_job_status(wizard_cluster: Cluster) -> None:
    action = await wizard_cluster.actions.get(name__eq="wizard_fail")

    async with action.pre_process.flow() as flow:
        unit = flow.units[0]
        assert isinstance(unit, OperationUnit)
        with pytest.raises(UnitExecutionError, match='finished with the status "failed"'):
            await unit.execute()


async def _test_action_flow_fail_status_code(action: Action) -> None:
    flow = await action.pre_process.init()
    unit = flow.units[1]
    assert isinstance(unit, OperationUnit)
    with pytest.raises(UnitExecutionError, match="Only current step can be submitted"):
        await unit.execute()


async def _skip_unit_from_outside(flow: Flow, unit_id: int) -> None:
    await flow.requester.post(
        *flow.get_own_path(),
        "operation",
        data={
            "method": "skip_step",
            "params": {"stepId": unit_id, "processSyncKey": flow._sync_key},
        },
    )


async def _test_execute_unit_with_wrong_synk_key(action: Action) -> None:
    async with action.pre_process.flow() as flow:
        unit1, unit2, *_ = flow.units
        assert isinstance(unit2, OperationUnit)
        await _skip_unit_from_outside(flow=flow, unit_id=unit1.id)

        with pytest.raises(UnitExecutionError, match="Can't find Process"):
            await unit2.execute()


async def _test_skip_unit_with_wrong_synk_key(action: Action) -> None:
    async with action.pre_process.flow() as flow:
        unit1, unit2, *_ = flow.units
        assert isinstance(unit2, OperationUnit)
        await _skip_unit_from_outside(flow=flow, unit_id=unit1.id)

        assert await unit2.skip() is False


async def _get_mapping_host_component_pairs(cluster: Cluster) -> list[tuple[int, int]]:
    response = await cluster.requester.get("clusters", cluster.id, "mapping")
    return [(entry["hostId"], entry["componentId"]) for entry in response.as_list()]


async def _prepare_cluster_mapping(cluster: Cluster, to_add: list[MappingPair], to_remove: list[MappingPair]) -> None:
    mapping = await cluster.mapping

    for component, host in to_add:
        await mapping.add(component=component, host=host)
    for component, host in to_remove:
        await mapping.remove(component=component, host=host)

    await mapping.save()


async def _prepare_mapping_entries(
    adcm_client: ADCMClient,
    cluster: Cluster,
    hostprovider: Bundle,
) -> tuple[Component, Component, Component, Host, Host]:
    service = await cluster.services.get(name__eq="service_1")
    component1 = await service.components.get(name__eq="component_1")
    component2 = await service.components.get(name__eq="component_2")
    component3 = await service.components.get(name__eq="component_3")
    provider = await adcm_client.hostproviders.create(
        bundle=hostprovider,
        name="WizardHP",
    )
    host_map1 = await adcm_client.hosts.create(
        hostprovider=provider,
        name="w-host1",
        cluster=cluster,
    )
    host_map2 = await adcm_client.hosts.create(
        hostprovider=provider,
        name="w-host2",
        cluster=cluster,
    )
    return component1, component2, component3, host_map1, host_map2


async def _test_mapping_happy_path(
    action: Action,
    cluster: Cluster,
    component1: Component,
    component2: Component,
    host_map1: Host,
    host_map2: Host,
) -> None:
    flow = await action.pre_process.init()
    unit1, unit2 = flow.units
    assert isinstance(unit1, MappingUnit)
    assert isinstance(unit2, MappingUnit)
    # mapping of first unit
    mapping = await unit1.mapping
    # check delta calculating
    await mapping.remove(component1, host_map1)
    await mapping.remove(component1, host_map1)
    await mapping.add(component2, host_map2)
    await mapping.remove(component2, host_map2)
    expected_delta = {
        "add": [],
        "remove": [{"hostId": host_map1.id, "componentId": component1.id}],
    }
    assert mapping._delta_to_payload() == expected_delta, "first step delta is wrong"
    await unit1.execute()
    # mapping of second unit
    mapping = await unit2.mapping
    await mapping.add(component=[component2], host=[host_map1, host_map2])
    await unit2.execute()
    # check a process was completed
    await flow.complete()
    stage = await flow.get_state()
    assert stage == "completed"
    mapping_job = await action.run(process=flow)
    await mapping_job.wait()
    # check a mapping record after the action
    expected_mapping_pairs = [
        (host_map1.id, component2.id),
        (host_map2.id, component2.id),
    ]
    mapping = await _get_mapping_host_component_pairs(cluster)
    assert mapping == expected_mapping_pairs


async def _test_mapping_rules_contradiction(
    action: Action,
    component: Component,
    host_map: Host,
) -> None:
    flow = await action.pre_process.init()
    unit1, unit2 = flow.units
    assert isinstance(unit1, MappingUnit) and isinstance(unit2, MappingUnit)
    mapping = await unit1.mapping
    await mapping.add(component, host_map)
    with pytest.raises(UnitExecutionError):
        await unit1.execute()


async def test_action_flow(
    adcm_client: ADCMClient,
    wizard_cluster: Cluster,
    simple_hostprovider_bundle: Bundle,
) -> None:
    action = await wizard_cluster.actions.get(name__eq="wizard_jinja")
    await _test_action_flow_success(action)
    await _test_action_flow_fail_context_manager(action)
    await _test_action_flow_fail_timeout(adcm_client, wizard_cluster, action)
    await _test_action_flow_fail_status_code(action)
    await _test_action_flow_fail_job_status(wizard_cluster)
    await _test_execute_unit_with_wrong_synk_key(action)
    await _test_skip_unit_with_wrong_synk_key(action)

    # mapping tests
    component1, component2, component3, host_map1, host_map2 = await _prepare_mapping_entries(
        adcm_client, wizard_cluster, simple_hostprovider_bundle
    )
    await _prepare_cluster_mapping(cluster=wizard_cluster, to_add=[(component1, host_map1)], to_remove=[])

    mapping_action = await wizard_cluster.actions.get(name__eq="wizard_with_mapping")
    await _test_mapping_happy_path(
        action=mapping_action,
        cluster=wizard_cluster,
        component1=component1,
        component2=component2,
        host_map1=host_map1,
        host_map2=host_map2,
    )
    await _test_mapping_rules_contradiction(action=mapping_action, component=component3, host_map=host_map1)


async def test_configuration_unit(wizard_cluster: Cluster, httpx_client: AsyncClient) -> None:
    action = await wizard_cluster.actions.get(name__eq="single_config_step")

    flow = await action.pre_process.init()
    assert len(flow.units) == 1
    unit = flow.units[0]
    assert isinstance(unit, ConfigurationUnit)

    process_url = "/".join(str(item) for item in flow.get_own_path()) + "/"
    response = await httpx_client.get(process_url)
    assert response.json()["currentStep"] == unit.id
    assert response.json()["state"] == "created"

    config = await unit.config
    config["integer_field", Parameter].set("wrong value")

    with pytest.raises(
        UnitExecutionError,
        match="<ConfigurationUnit #1 Stage1.ConfigurationStep1>.*"
        r"integer_field \[value\]: should be of type integer",
    ):
        await unit.execute()

    int_value = 123
    config["integer_field", Parameter].set(value=int_value)
    await unit.execute()

    step_url = f"{process_url}/steps/{unit.id}/"
    response = await httpx_client.get(step_url)
    assert response.json()["configuration"]["config"]["integer_field"] == int_value

    response = await httpx_client.get(process_url)
    assert response.json()["currentStep"] is None
    assert response.json()["state"] == "created"

    await flow.complete()
    response = await httpx_client.get(process_url)
    assert response.json()["currentStep"] is None
    assert response.json()["state"] == "completed"
