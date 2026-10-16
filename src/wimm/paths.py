import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
APP_DIRECTORY = "where-is-my-memory"


@dataclass(frozen=True)
class UserPaths:
    """Explicit per-user directories, injectable without changing XDG variables."""

    config_dir: Path
    state_dir: Path
    cache_dir: Path


def default_user_paths() -> UserPaths:
    """Return application directories resolved by GLib.

    Returns
    -------
    UserPaths
        Configuration, state and cache directories for the application.

    Notes
    -----
    GLib reads XDG variables once per process. Tests therefore pass explicit
    UserPaths instead of changing the environment to influence GLib.
    """
    from gi.repository import GLib

    return UserPaths(
        config_dir=Path(GLib.get_user_config_dir()) / APP_DIRECTORY,
        state_dir=Path(GLib.get_user_state_dir()) / APP_DIRECTORY,
        cache_dir=Path(GLib.get_user_cache_dir()) / APP_DIRECTORY,
    )


def ensure_private_dir(path: Path) -> None:
    """Create or secure a directory, refusing a symlink at the target.

    Parameters
    ----------
    path : Path
        Directory to create with explicit private permissions.

    Notes
    -----
    Parent symlinks are allowed for normal XDG directory layouts.
    """
    if path.is_symlink():
        raise ValueError("Private directory must not be a symlink")
    os.makedirs(name=path, mode=PRIVATE_DIR_MODE, exist_ok=True)
    os.chmod(path=path, mode=PRIVATE_DIR_MODE, follow_symlinks=False)


def _open_private_stream(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path=path, flags=flags, mode=PRIVATE_FILE_MODE)
    try:
        return os.fdopen(fd, mode="wb")
    except BaseException:
        os.close(fd)
        raise


def _sync_directory(path: Path) -> None:
    fd = os.open(path=path, flags=os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd=fd)
    finally:
        os.close(fd)


def write_private_atomic(path: Path, data: bytes) -> None:
    """Replace a file atomically using a private temporary file beside it.

    Parameters
    ----------
    path : Path
        Destination in an existing directory.
    data : bytes
        Complete new contents; failures before replacement preserve the destination.

    Notes
    -----
    Parent symlinks are allowed for normal XDG directory layouts.
    """
    temporary = path.with_name(name=f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with _open_private_stream(path=temporary) as stream:
            os.fchmod(fd=stream.fileno(), mode=PRIVATE_FILE_MODE)
            stream.write(data)
            stream.flush()
            os.fsync(fd=stream.fileno())
        os.replace(src=temporary, dst=path)
        _sync_directory(path=path.parent)
    finally:
        temporary.unlink(missing_ok=True)
