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

from pathlib import Path

import yaml


def create_yaml(data: list | dict, path: Path) -> None:
    """
    :param data: desired .yaml file content
    :param path: target .yaml path
    """
    if path.suffix not in {".yaml", ".yml"}:
        raise ValueError(f"Invalid .yaml/.yml path: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as yaml_file:
        yaml.dump(data, yaml_file, default_flow_style=False)
