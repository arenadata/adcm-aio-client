from typing import Any, Self

from adcm_aio_client.core.requesters import Requester
from adcm_aio_client.core.types import AwareOfOwnPath, WithRequester


class InteractiveObject(WithRequester, AwareOfOwnPath):
    def __init__(self: Self, requester: Requester, data: dict[str, Any]) -> None:
        self._requester = requester
        self._data = data

    def _construct[Object: "InteractiveObject"](self: Self, what: type[Object], from_data: dict[str, Any]) -> Object:
        return what(requester=self._requester, data=from_data)

    def _construct_child[Child: "InteractiveChildObject"](
        self: Self, what: type[Child], from_data: dict[str, Any]
    ) -> Child:
        return what(requester=self._requester, data=from_data, parent=self)


class InteractiveChildObject[Parent](InteractiveObject):
    def __init__(self: Self, parent: Parent, requester: Requester, data: dict[str, Any]) -> None:
        super().__init__(requester=requester, data=data)
        self._parent = parent
