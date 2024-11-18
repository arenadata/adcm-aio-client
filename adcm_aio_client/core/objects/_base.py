from typing import Any, Self

from adcm_aio_client.core.requesters import Requester
from adcm_aio_client.core.types import AwareOfOwnPath, Endpoint, WithRequester


class InteractiveObject(WithRequester, AwareOfOwnPath):
    def __init__(self: Self, requester: Requester, data: dict[str, Any]) -> None:
        self._requester = requester
        self._data = data

    @property
    def id(self: Self) -> int:
        # it's the default behavior, without id many things can't be done
        return int(self._data["id"])

    async def refresh(self: Self) -> Self:
        response = await self._requester.get(*self.get_own_path())
        self._data = response.as_dict()
        # todo drop caches

        return self

    def _construct[Object: "InteractiveObject"](self: Self, what: type[Object], from_data: dict[str, Any]) -> Object:
        return what(requester=self._requester, data=from_data)

    def _construct_child[Child: "InteractiveChildObject"](
        self: Self, what: type[Child], from_data: dict[str, Any]
    ) -> Child:
        return what(requester=self._requester, data=from_data, parent=self)


class RootInteractiveObject(InteractiveObject):
    PATH_PREFIX: str

    def get_own_path(self: Self) -> Endpoint:
        return self.PATH_PREFIX, self.id


class InteractiveChildObject[Parent](InteractiveObject):
    def __init__(self: Self, parent: Parent, requester: Requester, data: dict[str, Any]) -> None:
        super().__init__(requester=requester, data=data)
        self._parent = parent
