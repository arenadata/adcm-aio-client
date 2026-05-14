import pytest
import pytest_asyncio

from adcm_aio_client import Filter
from adcm_aio_client.client import ADCMClient
from adcm_aio_client.errors import ConflictError
from adcm_aio_client.objects import Action, Bundle, Cluster, Flow

pytestmark = [pytest.mark.asyncio]

STEPS_COUNT_IN_WIZARD_ACTION = 3


@pytest_asyncio.fixture()
async def wizard_cluster(adcm_client: ADCMClient, wizard_cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=wizard_cluster_bundle, name="Awesome Cluster")
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="service_1"))
    return cluster


@pytest_asyncio.fixture()
async def action(wizard_cluster: Cluster) -> Action:
    return await wizard_cluster.actions.get(name__eq="wizard_jinja")


async def test_action_flow(action: Action) -> None:
    # check a flow creating
    flow = await action.pre_process.init()
    assert isinstance(flow, Flow)

    # check getting units
    units = flow.units
    assert len(units) == STEPS_COUNT_IN_WIZARD_ACTION
    first_step = units[0]
    assert first_step["name"] == "stage1_step1"
    assert first_step["stage"] == "First stage"

    # check working with the context manager, will update
    with pytest.raises(ConflictError, match="All steps must be completed"):
        async with action.pre_process.flow() as flow:
            assert flow


@pytest.mark.skip(reason="flow.complete() doesn't complete with HTTP 200 yet")
async def test_action_flow_context_manager(action: Action) -> None:
    # to run the test, need to add steps in the wizard action that can complete or skip (ADCM-8027)
    async with action.pre_process.flow() as flow:
        assert flow
