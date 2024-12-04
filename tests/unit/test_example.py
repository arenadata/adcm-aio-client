from adcm_aio_client.core.objects.cm import Cluster, ServicesNode
from adcm_aio_client.core.types import Requester

async def test_filters(queue_requester: Requester) -> None:
    cluster = Cluster(data={"id": 4}, requester=queue_requester)
    await cluster.services.filter({"status__eq": "sdflkj", "name__in": ("ADH", )})
