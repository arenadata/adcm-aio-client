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

from adcm_aio_client.mapping._types import LocalMappings, MappingData


def apply_local_changes(local: LocalMappings, remote: MappingData) -> MappingData:
    all_entries = local.current | remote
    removed_locally = local.initial - local.current
    return all_entries - removed_locally


def apply_remote_changes(local: LocalMappings, remote: MappingData) -> MappingData:
    all_entries = local.current | remote
    removed_in_remotely = local.initial - remote
    return all_entries - removed_in_remotely
