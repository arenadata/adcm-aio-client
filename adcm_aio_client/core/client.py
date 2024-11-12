from adcm_aio_client.core.objects import ClustersNode
from adcm_aio_client.core.requesters import Requester


class ADCMClient:
    def __init__(self, requester: Requester) -> None:
        self._requester = requester
        self.clusters = ClustersNode(requester=self._requester)
