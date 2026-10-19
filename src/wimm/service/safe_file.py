"""Unlink of one planned file below a root, through descriptors and without following links."""

import errno
import os
import stat

from .errors import TargetChanged
from .safe_tree import BLOCK_BYTES, DIR_FLAGS, TreeRemoval


def _open_parents(*, root: str, parts: list[str]) -> int:
    fd = os.open(root, DIR_FLAGS)
    try:
        for part in parts:
            try:
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise TargetChanged(f"{part} is not a plain directory under {root}") from error
                raise
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def remove_file(*, root: str, relative: str, st_ino: int, st_dev: int) -> TreeRemoval:
    """Unlink one planned file below `root`, following no link: else `TargetChanged`.

    A missing file raises `FileNotFoundError`."""
    *parents, name = relative.split("/")
    if any(part in ("", "..", ".") for part in (*parents, name)):
        raise TargetChanged(f"{relative} is not a path inside {root}")
    parent = _open_parents(root=root, parts=parents)
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_ino, info.st_dev) != (st_ino, st_dev):
            raise TargetChanged(f"{relative} is not the file the plan showed")
        os.unlink(name, dir_fd=parent)
    finally:
        os.close(parent)
    freed = info.st_blocks * BLOCK_BYTES if info.st_nlink == 1 else 0
    return TreeRemoval(removed=1, freed_bytes=freed)
