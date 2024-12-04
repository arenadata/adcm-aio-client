from adcm_aio_client.core.mapping.types import LocalMappings, MappingData

type Added = MappingData
type Removed = MappingData


def apply_local_changes(local: LocalMappings, remote: MappingData) -> MappingData:
    if local.initial == remote:
        return local.current

    local_added, local_removed = _find_difference(previous=local.initial, current=local.current)

    remote |= local_added
    remote -= local_removed

    return remote


def apply_remote_changes(local: LocalMappings, remote: MappingData) -> MappingData:
    local_added, local_removed = _find_difference(previous=local.initial, current=local.current)

    remote_added, remote_removed = _find_difference(previous=local.initial, current=remote)

    to_add = local_added - remote_removed
    to_remove = local_removed - remote_added

    remote |= to_add
    remote -= to_remove

    return remote


def _find_difference(previous: MappingData, current: MappingData) -> tuple[Added, Removed]:
    added = current - previous
    removed = previous - current

    return added, removed
