from pathlib import Path
from tarfile import TarFile

def pack_bundle(from_dir: Path, to: Path) -> Path:
    archive = (to / from_dir.name).with_suffix(".tgz")

    with TarFile(name=archive, mode="w") as tar:
        for entry in from_dir.iterdir():
            tar.add(entry)

    return archive



