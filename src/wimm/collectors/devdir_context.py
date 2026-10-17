"""Observe the disk around a candidate dependency folder, for ``classify_devdir``.

The one place that builds a ``DevdirContext``: the scan and the executor both call it, so
what the scan offered and what the executor accepts are decided on the same facts. Nothing
is followed through a symlink and no external program is run (``git`` would execute
``core.fsmonitor``): ``.gitignore`` is read as plain text.
"""

import os
import stat
from pathlib import Path

from wimm.core.devdir_rules import CACHEDIR_TAG, VENV_MARKER, DevdirContext

GITIGNORE_NAME = ".gitignore"
# A larger file is treated as absent: cutting it could turn `target-old` into `target`.
GITIGNORE_MAX_BYTES = 64 * 1024


def _is_regular_file(*, path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _read_gitignore(*, path: Path) -> str:
    """The text of a real, small ``.gitignore``; empty for anything else."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > GITIGNORE_MAX_BYTES:
            return ""
        try:
            return handle.read(GITIGNORE_MAX_BYTES).decode("utf-8", errors="replace")
        except OSError:
            return ""


def _same_folder(*, first: Path, second: Path) -> bool:
    return os.path.realpath(first) == os.path.realpath(second)


def read_devdir_context(*, path: Path, home: Path) -> DevdirContext:
    """Describe what sits around the candidate folder ``path``.

    Raises
    ------
    OSError
        If the parent folder cannot be listed: the caller decides whether that counts as an
        error to report (scan) or a reason to refuse (executor).
    """
    parent = path.parent
    with os.scandir(parent) as iterator:
        entries = frozenset(entry.name for entry in iterator)
    return DevdirContext(
        parent_entries=entries,
        has_cachedir_tag=_is_regular_file(path=path / CACHEDIR_TAG),
        has_pyvenv_cfg=_is_regular_file(path=path / VENV_MARKER),
        gitignore_text=_read_gitignore(path=parent / GITIGNORE_NAME)
        if GITIGNORE_NAME in entries
        else "",
        parent_is_home=_same_folder(first=parent, second=home),
    )
