from adcm_aio_client.mapping._types import LocalMappings, MappingData


def apply_local_changes(local: LocalMappings, remote: MappingData) -> MappingData:
    all_entries = local.current | remote
    removed_locally = local.initial - local.current
    return all_entries - removed_locally


def apply_remote_changes(local: LocalMappings, remote: MappingData) -> MappingData:
    all_entries = local.current | remote
    removed_in_remotely = local.initial - remote
    return all_entries - removed_in_remotely
