from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.actions._objects import ConfigurationUnit, Flow, OperationUnit
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import Parameter
from adcm_aio_client.errors import UnitExecutionError, WaitTimeoutError
from adcm_aio_client.objects import Action, Bundle, Cluster

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
    # check the data definition for steps
    assert unit1.name == "stage1_step1"
    assert unit1.stage == "First stage"
    assert unit3.stage == "Second stage"
    # check execute and skip units
    await unit1.execute()
    assert await unit2.skip() is True  # pyright: ignore[reportAttributeAccessIssue]
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
        with pytest.raises(UnitExecutionError, match='finished with the status "failed"'):
            await unit.execute()


async def _test_action_flow_fail_status_code(action: Action) -> None:
    flow = await action.pre_process.init()
    unit = flow.units[1]
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
        await _skip_unit_from_outside(flow=flow, unit_id=unit1.id)

        with pytest.raises(UnitExecutionError, match="Can't find Process"):
            await unit2.execute()


async def _test_skip_unit_with_wrong_synk_key(action: Action) -> None:
    async with action.pre_process.flow() as flow:
        unit1, unit2, *_ = flow.units
        await _skip_unit_from_outside(flow=flow, unit_id=unit1.id)

        assert await unit2.skip() is False  # pyright: ignore[reportAttributeAccessIssue]


async def test_action_flow(adcm_client: ADCMClient, wizard_cluster: Cluster) -> None:
    action = await wizard_cluster.actions.get(name__eq="wizard_jinja")
    await _test_action_flow_success(action)
    await _test_action_flow_fail_context_manager(action)
    await _test_action_flow_fail_timeout(adcm_client, wizard_cluster, action)
    await _test_action_flow_fail_status_code(action)
    await _test_action_flow_fail_job_status(wizard_cluster)
    await _test_execute_unit_with_wrong_synk_key(action)
    await _test_skip_unit_with_wrong_synk_key(action)


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
        r"CONFIG_VALUE_ERROR.*/integer_field \[value\]: should be of type integer",
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
