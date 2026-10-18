"""Facts about a candidate development root, read from disk for `core.root_policy` (ADR-007)."""

import logging
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wimm.collectors.root_candidates import MOUNTINFO_SEPARATOR, MOUNTPOINT_FIELD, read_mountinfo
from wimm.core.root_policy import DirFacts, RootFacts

__all__ = ["read_root_facts"]

LOGGER = logging.getLogger(__name__)
MOUNT_OPTIONS_FIELD = 5
SUPER_OPTIONS_FIELD = 2
READ_ONLY_OPTION = "ro"
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


@dataclass(frozen=True)
class _Mount:
    point: Path
    fstype: str
    read_only: bool


def _parse_mounts(*, text: str) -> tuple[_Mount, ...]:
    """Mounts with their type and `ro` option; malformed lines are dropped."""
    mounts = []
    for line in text.splitlines():
        head, separator, tail = line.partition(MOUNTINFO_SEPARATOR)
        fields, types = head.split(), tail.split()
        if not separator or len(fields) <= MOUNT_OPTIONS_FIELD or not types:
            continue
        point = _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), fields[MOUNTPOINT_FIELD])
        # Per-mount options, then the superblock ones after the separator (errors=remount-ro).
        options = fields[MOUNT_OPTIONS_FIELD].split(",")
        options += types[SUPER_OPTIONS_FIELD].split(",") if len(types) > SUPER_OPTIONS_FIELD else []
        mounts.append(_Mount(Path(point), types[0], READ_ONLY_OPTION in options))
    return tuple(mounts)


def _mount_of(*, real: Path, mounts: tuple[_Mount, ...]) -> _Mount | None:
    """The mount holding `real`: longest mount point, a later mount on the same point wins."""
    containing = [mount for mount in mounts if real.is_relative_to(mount.point)]
    if not containing:
        return None
    return max(reversed(containing), key=lambda mount: len(mount.point.parts))


def _dir_facts(*, info: os.stat_result) -> DirFacts:
    return DirFacts(uid=info.st_uid, gid=info.st_gid, mode=info.st_mode)


def _read_chain(
    *, path: Path, read_stat: Callable[[Path], os.stat_result]
) -> tuple[os.stat_result, Path, os.stat_result, tuple[DirFacts, ...]] | None:
    """lstat of `path`, its realpath, the real root's stat and the ancestors from `/`."""
    try:
        link_info = read_stat(path)
        real = Path(os.path.realpath(path))
        root_info = read_stat(real)
        ancestors = tuple(_dir_facts(info=read_stat(parent)) for parent in reversed(real.parents))
    except OSError as error:
        LOGGER.debug("Cannot read the facts of %s: %s", path, error)
        return None
    return link_info, real, root_info, ancestors


def read_root_facts(
    *,
    path: Path,
    read_stat: Callable[[Path], os.stat_result] = os.lstat,
    read_mounts: Callable[[], str] = read_mountinfo,
) -> RootFacts | None:
    """Observe `path` as a candidate root; None when missing, unreadable or in no mount.

    None is never "allowed": the caller must treat it as a refusal when it acts.
    """
    chain = _read_chain(path=path, read_stat=read_stat)
    if chain is None:
        return None
    link_info, real, root_info, ancestors = chain
    mount = _mount_of(real=real, mounts=_parse_mounts(text=read_mounts()))
    if mount is None:
        return None
    return RootFacts(
        realpath=real,
        is_symlink=stat.S_ISLNK(link_info.st_mode),
        st_uid=root_info.st_uid,
        st_gid=root_info.st_gid,
        own_uid=os.getuid(),
        own_gid=os.getgid(),
        mode=root_info.st_mode,
        ancestors=ancestors,
        fstype=mount.fstype,
        read_only=mount.read_only,
    )
