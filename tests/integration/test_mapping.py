import pytest
from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.objects.cm import Cluster

@pytest.fixture()
def cluster(adcm_client: ADCMClient) -> Cluster:
    ...

def test_cluster_mapping(cluster: Cluster):
    ...
