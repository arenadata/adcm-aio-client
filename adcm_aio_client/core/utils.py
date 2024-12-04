from typing import Awaitable, Iterable
import asyncio

from adcm_aio_client.core.objects._base import InteractiveObject
from adcm_aio_client.core.types import RequesterResponse


async def safe_gather(
    coros: Iterable[Awaitable[RequesterResponse]], objects: Iterable[InteractiveObject]
) -> set[InteractiveObject]:
    """
    Performs asyncio.gather() on coros.
    Coros must be in corresponding order with the objects, from which coros was made
    Returns objects that caused errors
    """
    results = await asyncio.gather(*coros, return_exceptions=True)

    errors = set()
    for object_, result in zip(objects, results):
        if isinstance(result, Exception):
            errors.add(object_)

    return errors
