from adcm_aio_client.core.filters import Filter
from adcm_aio_client.core.objects.cm import Cluster, ServicesNode
from adcm_aio_client.core.types import Requester

async def test_filters(queue_requester: Requester) -> None:
    cluster = Cluster(data={"id": 4}, requester=queue_requester)
    await cluster.services.filter(Filter(attr="name", op="eq", value="ADH"))
