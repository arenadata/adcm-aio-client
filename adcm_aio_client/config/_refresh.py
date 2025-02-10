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

from adcm_aio_client.config._operations import find_config_difference
from adcm_aio_client.config._types import ConfigData, ConfigSchema, LevelNames, LocalConfigs, ParameterChange


def apply_local_changes(local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
    if local.initial.id == remote.id:
        return local.changed

    local_diff = find_config_difference(previous=local.initial, current=local.changed, schema=schema)
    if not local_diff:
        # no changed, nothing to apply
        return remote

    _apply(data=remote, changes=local_diff)

    return remote


def apply_remote_changes(local: LocalConfigs, remote: ConfigData, schema: ConfigSchema) -> ConfigData:
    if local.initial.id == remote.id:
        return remote

    local_diff = find_config_difference(previous=local.initial, current=local.changed, schema=schema)
    if not local_diff:
        return remote

    remote_diff = find_config_difference(previous=local.initial, current=remote, schema=schema)

    changed_in_remote = set(remote_diff.keys())
    only_local_changes = {k: v for k, v in local_diff.items() if k not in changed_in_remote}

    _apply(data=remote, changes=only_local_changes)

    return remote


def _apply(data: ConfigData, changes: dict[LevelNames, ParameterChange]) -> None:
    for parameter_name, change in changes.items():
        if "value" in change.current:
            cur_value = change.current["value"]
            data.set_value(parameter=parameter_name, value=cur_value)

        for name, value in change.current.get("attrs", {}).items():
            data.set_attribute(parameter=parameter_name, attribute=name, value=value)
