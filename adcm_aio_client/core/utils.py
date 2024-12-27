from collections.abc import Awaitable, Iterable
import asyncio

from adcm_aio_client.core.types import RequesterResponse


async def safe_gather(coros: Iterable[Awaitable[RequesterResponse]], msg: str) -> ExceptionGroup | None:
    """
    Performs asyncio.gather() on coros, returns combined in ExceptionGroup errors
    """
    results = await asyncio.gather(*coros, return_exceptions=True)
    exceptions = [res for res in results if isinstance(res, Exception)]

    if exceptions:
        return ExceptionGroup(msg, exceptions)

    return None
