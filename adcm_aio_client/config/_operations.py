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

from contextlib import suppress

from adcm_aio_client.config._types import ConfigSchema, GenericConfigData, LevelNames, ParameterChange


# Difference
def find_config_difference(
    previous: GenericConfigData, current: GenericConfigData, schema: ConfigSchema
) -> dict[LevelNames, ParameterChange]:
    diff = {}

    for names, _ in schema.iterate_parameters():
        prev = {"value": None, "attrs": {}}
        cur = {"value": None, "attrs": {}}

        # TypeError / KeyError may occur when `None` is in values
        # (e.g. structure with dict as root item and with None value)
        if not schema.is_group(names):
            with suppress(TypeError, KeyError):
                prev["value"] = previous.get_value(names)

            with suppress(TypeError, KeyError):
                cur["value"] = current.get_value(names)
        else:
            prev.pop("value")
            cur.pop("value")

        attr_key = f"/{'/'.join(names)}"
        prev["attrs"] = previous.attributes.get(attr_key, {})
        cur["attrs"] = current.attributes.get(attr_key, {})

        if prev != cur:
            diff[names] = ParameterChange(previous=prev, current=cur)

    return diff
