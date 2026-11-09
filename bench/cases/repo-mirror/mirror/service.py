import tempfile
from pathlib import Path

from git import Repo

MIRRORS = Path(tempfile.gettempdir()) / "mirrors"


def create_mirror(url: str, name: str) -> str:
    dest = MIRRORS / name
    Repo.clone_from(url, dest, mirror=True)
    return str(dest)
