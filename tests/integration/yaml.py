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
