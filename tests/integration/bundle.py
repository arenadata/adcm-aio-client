from pathlib import Path
from tarfile import TarFile
from typing import Any
import shutil

import yaml

from adcm_aio_client.core.client import ADCMClient
from adcm_aio_client.core.objects.cm import Bundle


def pack_bundle(from_dir: Path, to: Path) -> Path:
    archive = (to / from_dir.name).with_suffix(".tar")

    with TarFile(name=archive, mode="w") as tar:
        for entry in from_dir.iterdir():
            tar.add(entry, arcname=entry.name)

    return archive


def modify_yaml_field(
    yaml_content: list[dict[str, Any]], target_name: str, field_to_modify: str, new_value: str | int
) -> dict[str, Any]:
    for entry in yaml_content:
        # Check if the entry matches the specified 'name'
        if entry.get(target_name) == field_to_modify:
            entry[target_name] = new_value
            return entry
    raise ValueError(f"Field '{field_to_modify}' not found in config.yaml")


async def create_bundles_by_template(
    adcm_client: ADCMClient,
    tmp_path: Path,
    path_to_template_bundle: Path,
    target_name: str,
    field_to_modify: str,
    new_value: str,
    number_of_bundles: int,
) -> list[Bundle]:
    created_bundles = []
    for i in range(number_of_bundles):
        # Create a new path for the temporary bundle
        new_bundle_path = tmp_path / f"{path_to_template_bundle.name}_{i}"

        # Copy the whole directory of the template bundle to the new path
        shutil.copytree(path_to_template_bundle, new_bundle_path)

        # Update the yaml field in the new config
        new_config_path = new_bundle_path / "config.yaml"
        with Path.open(new_config_path) as file:
            new_config_data = yaml.safe_load(file)

        modify_yaml_field(
            new_config_data, target_name=target_name, field_to_modify=field_to_modify, new_value=f"{new_value}_{i}"
        )

        with Path.open(new_config_path, "w") as file:
            yaml.dump(new_config_data, file)

        (tmp_path / f"{new_bundle_path.name}_packed").mkdir()
        bundle_path = pack_bundle(from_dir=new_bundle_path, to=(tmp_path / f"{new_bundle_path.name}_packed"))
        created_bundle = await adcm_client.bundles.create(source=bundle_path, accept_license=False)
        created_bundles.append(created_bundle)

    return created_bundles
