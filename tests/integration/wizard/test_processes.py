from httpx import AsyncClient
import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.actions._objects import ConfigurationUnit, OperationUnit
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.config import Parameter
from adcm_aio_client.errors import ConflictError, UnitExecutionError, WaitTimeoutError
from adcm_aio_client.objects import Action, Bundle, Cluster

pytestmark = [pytest.mark.asyncio]

OPERATION_STEPS_COUNT = 2
SUCCESS_TIMEOUT = 5
FAIL_TIMEOUT = 1


@pytest_asyncio.fixture()
async def wizard_cluster(adcm_client: ADCMClient, wizard_cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=wizard_cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="service_1"))
    return cluster


async def _test_action_flow_success(action: Action) -> None:
    async with action.pre_process.flow() as flow:
        units = flow.units
        assert len(units) == OPERATION_STEPS_COUNT

        first_step = units[0]
        assert first_step.name == "stage1_step1"
        assert first_step.stage == "First stage"

        for unit in units:
            assert isinstance(unit, OperationUnit)
            await unit.execute(timeout=SUCCESS_TIMEOUT)


async def _test_action_flow_fail_context_manager(action: Action) -> None:
    with pytest.raises(ConflictError, match="All steps must be completed"):
        async with action.pre_process.flow() as flow:
            assert flow


async def _test_action_flow_fail_timeout(action: Action) -> None:
    with pytest.raises(WaitTimeoutError):
        async with action.pre_process.flow() as flow:
            for unit in flow.units:
                await unit.execute(timeout=FAIL_TIMEOUT)


async def _test_action_flow_fail_job_status(action: Action) -> None:
    with pytest.raises(UnitExecutionError, match='finished with the status "failed"'):
        flow = await action.pre_process.init()
        unit = flow.units[0]
        await unit.execute()


async def test_action_flow(wizard_cluster: Cluster) -> None:
    action = await wizard_cluster.actions.get(name__eq="wizard_jinja")
    await _test_action_flow_success(action)
    await _test_action_flow_fail_context_manager(action)
    await _test_action_flow_fail_timeout(action)

    action_with_fail_step = await wizard_cluster.actions.get(name__eq="wizard_fail")
    await _test_action_flow_fail_job_status(action_with_fail_step)


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

    with pytest.raises(ConflictError, match=r"CONFIG_VALUE_ERROR.*/integer_field \[value\]: should be of type integer"):
        await unit.execute()

    config["integer_field", Parameter].set(123)
    await unit.execute()

    response = await httpx_client.get(process_url)
    assert response.json()["currentStep"] is None
    assert response.json()["state"] == "created"

    await flow.complete()
    response = await httpx_client.get(process_url)
    assert response.json()["currentStep"] is None
    assert response.json()["state"] == "completed"
