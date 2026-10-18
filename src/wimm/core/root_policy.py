"""ADR-007: which directories may be a development root. Pure: the caller gathers the facts."""

import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from wimm.i18n import N_

from . import constants as c

__all__ = ["ROOT_REFUSAL_MESSAGES", "DirFacts", "RootFacts", "RootRefusal", "root_refusal"]

ROOT_UID = 0
ROOT_GID = 0


class RootRefusal(Enum):
    """Why a directory cannot be a root, in the order the checks run."""

    SYMLINK = "symlink"
    TOO_SHALLOW = "too_shallow"
    SYSTEM_PATH = "system_path"
    HOME_ANCESTOR = "home_ancestor"
    OTHER_HOME = "other_home"
    NOT_OWNED = "not_owned"
    UNSAFE_PARENT = "unsafe_parent"
    REMOTE_FS = "remote_fs"
    READ_ONLY = "read_only"


ROOT_REFUSAL_MESSAGES: dict[RootRefusal, str] = {
    RootRefusal.SYMLINK: N_("La cartella è un collegamento simbolico: indica la cartella vera"),
    RootRefusal.TOO_SHALLOW: N_("La cartella è troppo vicina alla radice del disco"),
    RootRefusal.SYSTEM_PATH: N_("La cartella appartiene al sistema"),
    RootRefusal.HOME_ANCESTOR: N_("La cartella contiene la tua home"),
    RootRefusal.OTHER_HOME: N_("La cartella appartiene alla home di un altro utente"),
    RootRefusal.NOT_OWNED: N_("La cartella non è tua"),
    RootRefusal.UNSAFE_PARENT: N_(
        "Una cartella del percorso può essere modificata da altri utenti"
    ),
    RootRefusal.REMOTE_FS: N_("La cartella sta su un disco di rete o su un filesystem FUSE"),
    RootRefusal.READ_ONLY: N_("La cartella sta su un disco in sola lettura"),
}


@dataclass(frozen=True)
class DirFacts:
    """Owner, group and mode of one directory on the way from `/` to the root's parent."""

    uid: int
    gid: int
    mode: int


@dataclass(frozen=True)
class RootFacts:
    """What the caller observed about a candidate root (lstat, ancestors, mountinfo).

    `st_gid` is not in the ADR's list but the root itself obeys the same group rule as its
    ancestors, which needs its group.
    """

    realpath: Path
    is_symlink: bool
    st_uid: int
    st_gid: int
    own_uid: int
    own_gid: int
    mode: int
    ancestors: tuple[DirFacts, ...]
    fstype: str
    read_only: bool


def _is_unsafe_level(*, level: DirFacts, own_uid: int, own_gid: int) -> bool:
    """A directory others can rename entries in: foreign owner, or writable without sticky."""
    if level.uid not in (ROOT_UID, own_uid):
        return True
    if level.mode & stat.S_ISVTX:
        return False
    if level.mode & stat.S_IWOTH:
        return True
    return bool(level.mode & stat.S_IWGRP) and level.gid not in (ROOT_GID, own_gid)


def _is_remote(fstype: str) -> bool:
    return fstype in c.NETWORK_FSTYPES or fstype in c.FUSE_FSTYPES or fstype.startswith("fuse.")


def _is_system(real: Path) -> bool:
    return any(real.is_relative_to(prefix) for prefix in c.SYSTEM_PATH_PREFIXES)


def _position_refusal(*, real: Path, home: Path) -> RootRefusal | None:
    """Refusals by place. The home and everything below it are never refused here."""
    if real.is_relative_to(home):
        return None
    if home.is_relative_to(real) and real != home:
        return RootRefusal.HOME_ANCESTOR
    if len(real.parts) - 1 < c.ROOT_MIN_COMPONENTS:
        return RootRefusal.TOO_SHALLOW
    if _is_system(real):
        return RootRefusal.SYSTEM_PATH
    if len(home.parts) > 2 and real.is_relative_to(home.parent):
        return RootRefusal.OTHER_HOME
    return None


def _unsafe_chain(*, facts: RootFacts) -> bool:
    own = DirFacts(uid=facts.st_uid, gid=facts.st_gid, mode=facts.mode)
    levels = (*facts.ancestors, own)
    return any(
        _is_unsafe_level(level=level, own_uid=facts.own_uid, own_gid=facts.own_gid)
        for level in levels
    )


def root_refusal(*, facts: RootFacts, home: Path) -> RootRefusal | None:
    """The first reason `facts` cannot be a root, or None when it is allowed (ADR-007 order)."""
    if facts.is_symlink:
        return RootRefusal.SYMLINK
    position = _position_refusal(real=facts.realpath, home=home)
    if position is not None:
        return position
    if facts.st_uid != facts.own_uid:
        return RootRefusal.NOT_OWNED
    if _unsafe_chain(facts=facts):
        return RootRefusal.UNSAFE_PARENT
    if _is_remote(facts.fstype):
        return RootRefusal.REMOTE_FS
    return RootRefusal.READ_ONLY if facts.read_only else None
