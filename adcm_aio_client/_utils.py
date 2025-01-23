# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections.abc import Awaitable, Iterable
import asyncio

from adcm_aio_client._types import RequesterResponse


async def safe_gather(coros: Iterable[Awaitable[RequesterResponse]], msg: str) -> ExceptionGroup | None:
    """
    Performs asyncio.gather() on coros, returns combined in ExceptionGroup errors
    """
    results = await asyncio.gather(*coros, return_exceptions=True)
    exceptions = [res for res in results if isinstance(res, Exception)]

    if exceptions:
        return ExceptionGroup(msg, exceptions)

    return None
