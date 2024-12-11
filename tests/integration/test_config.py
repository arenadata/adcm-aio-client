from pathlib import Path

import pytest
import pytest_asyncio

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.config import Parameter, ParameterGroup, ActivatableParameterGroup
from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import Bundle, Cluster
from tests.integration.bundle import pack_bundle
from tests.integration.conftest import BUNDLES

pytestmark = [pytest.mark.asyncio]


@pytest_asyncio.fixture()
async def cluster_bundle(adcm_client: ADCMClient, tmp_path: Path) -> Bundle:
    bundle_path = pack_bundle(from_dir=BUNDLES / "complex_cluster", to=tmp_path)
    return await adcm_client.bundles.create(source=bundle_path, accept_license=True)


@pytest_asyncio.fixture()
async def cluster(adcm_client: ADCMClient, cluster_bundle: Bundle) -> Cluster:
    cluster = await adcm_client.clusters.create(bundle=cluster_bundle, name="Awesome Cluster") 
    await cluster.services.add(filter_=Filter(attr="name", op="eq", value="complex_config"))
    return cluster


async def test_config(cluster: Cluster) -> None:
    # save two configs for later refresh usage
    service = await cluster.services.get()
    config_1 = await service.config
    service = await cluster.services.get()
    config_2 = await service.config

    # change and save

    service = await cluster.services.get()
    config = await service.config

    field = config["Complexity Level"]
    assert isinstance(field, Parameter)
    assert field.value == 4
    field.set(100)
    assert field.value == 100
    assert field.value == config["complexity_level", Parameter].value

    field = config["country_codes"]
    # structure with "list" root is a parameter
    assert isinstance(field, Parameter)
    field.set([{"country": "Unknown", "code": 32}])

    group = config["A lot of text"]
    assert isinstance(group, ParameterGroup)
    
#    group_like = group["Group-like structure"]
#    # structure with "dict" root is a group
#    assert isinstance(group_like, ParameterGroup)
#    assert isinstance(group_like["quantity"], Parameter)
#    nested_group = group_like["nested"]
#    assert isinstance(nested_group, ParameterGroup)
#    nested_group["attr", Parameter].set("something")
#    nested_group["op", Parameter].set("good")

    field = group["big_text"]
    assert isinstance(field, Parameter)
    assert field.value is None
    new_value = "A lot of text\nOn multiple lines\n\tAnd it's perfectly fine\n"
    field.set(new_value)
    assert field.value == new_value

    field = config["from_doc", ParameterGroup]["Map Secrets"]
    assert isinstance (field, Parameter)
    assert field.value is None
    new_secret_map = {"pass1": "verysecret", "pass2": "evenmoresecret"}
    field.set(new_secret_map)

    config["agroup", ActivatableParameterGroup].activate()

    pre_save_id = config.id

    await config.save()

    assert config.id != pre_save_id
    assert config_1.id == pre_save_id
    assert config_2.id == pre_save_id

    # check values are updated, so values are encrypted coming from server
    field = config["from_doc", ParameterGroup]["Map Secrets"]
    assert field.value.keys() == new_secret_map.keys()  # type: ignore
    assert field.value.values() != new_secret_map.values()  # type: ignore

    # refresh

    non_conflicting_value_1 = 43.2
    non_conflicting_value_2 = "megapass"
    conflict_value_1 = "very fun\n"
    conflict_value_2 = 200

    for config_ in (config_1, config_2):
        config_["Set me", Parameter].set( non_conflicting_value_1)
        group_ = config_["a_lot_of_text", ParameterGroup]
        group_["pass", Parameter].set( non_conflicting_value_2)
        group_["big_text", Parameter].set(conflict_value_1)
        config_["Complexity Level", Parameter].set(conflict_value_2)
