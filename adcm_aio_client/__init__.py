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

"""
To start using ADCM AIO Client initialize `ADCMSession` with `Credentials`.

By entering it as a contextmanager you'll get `adcm_aio_client.client.ADCMClient` instance.

Use it to get objects that you want to interact with
or create the ones you're missing.

```python
creds = Credentials("admin", "admin")
async with ADCMSession(creds) as client:
    # Same as `*.filter(Filter(attr="name", op="contains", value="internal"))`
    internal_hosts = await client.hosts.filter(name__contains="internal")
    adb = await client.clusters.get(name__eq="ADB Dev Stand")
    await adb.hosts.add(internal_hosts)
```
"""
    

from adcm_aio_client._filters import Filter
from adcm_aio_client._session import ADCMSession
from adcm_aio_client._types import Credentials

__all__ = [
    "ADCMSession",
    "Credentials",
    "Filter",
]
