from typing import Self

from adcm_aio_client.core.objects._base import AwareOfOwnPath, WithRequester


class Deletable(WithRequester, AwareOfOwnPath):
    async def delete(self: Self) -> None:
        await self._requester.delete(*self.get_own_path())
