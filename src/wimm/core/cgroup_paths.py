import re
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import PurePosixPath

from wimm.model.raw import RawProcess

from .constants import (
    APP_SLICE,
    CGROUP_RECORD_PREFIX,
    FLATPAK_SCOPE_PREFIX,
    GNOME_SCOPE_PREFIX,
    SCOPE_SUFFIX,
    SERVICE_SUFFIX,
    SESSION_SLICE,
    SNAP_SCOPE_PREFIX,
    USER_UNIT_TEMPLATE,
)

UNIT_ESCAPE_PATTERN = re.compile(r"\\x([0-9a-fA-F]{2})")
HEX_BASE = 16
MATCH_CACHE_SIZE = 4096


def unescape_unit_name(name: str) -> str:
    """Decode systemd hexadecimal escapes before interpreting a unit name."""
    return UNIT_ESCAPE_PATTERN.sub(lambda match: chr(int(match[1], base=HEX_BASE)), name)


def components(proc: RawProcess) -> tuple[str, ...]:
    return _components_of(cgroup=proc.cgroup)


# Pure functions of a few hundred distinct strings, called tens of thousands of times per
# cycle: cached, with a bound so the resident memory stays flat (RNF-01, RNF-02).
@lru_cache(maxsize=MATCH_CACHE_SIZE)
def _components_of(*, cgroup: str) -> tuple[str, ...]:
    path = cgroup.removeprefix(CGROUP_RECORD_PREFIX)
    return tuple(unescape_unit_name(name=part) for part in path.split("/") if part)


@lru_cache(maxsize=MATCH_CACHE_SIZE)
def matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(name=name, pat=pattern) for pattern in patterns)


@lru_cache(maxsize=MATCH_CACHE_SIZE)
def basename(path: str) -> str:
    """Last component of a path, as PurePosixPath gives it; cached for the same reason."""
    return PurePosixPath(path).name


def scope_appid(scope: str) -> str | None:
    if scope.startswith(GNOME_SCOPE_PREFIX) and scope.endswith(SCOPE_SUFFIX):
        return (
            scope.removeprefix(GNOME_SCOPE_PREFIX)
            .removesuffix(SCOPE_SUFFIX)
            .rsplit("-", maxsplit=1)[0]
        )
    if scope.startswith(SNAP_SCOPE_PREFIX) and scope.endswith(SCOPE_SUFFIX):
        return scope.split(".")[1]
    if scope.startswith(FLATPAK_SCOPE_PREFIX) and scope.endswith(SCOPE_SUFFIX):
        return (
            scope.removeprefix(FLATPAK_SCOPE_PREFIX)
            .removesuffix(SCOPE_SUFFIX)
            .rsplit("-", maxsplit=1)[0]
        )
    return None


def is_direct_user_service(proc: RawProcess) -> bool:
    parts = components(proc=proc)
    return (
        len(parts) >= 3
        and parts[-3] == USER_UNIT_TEMPLATE.format(uid=proc.uid)
        and parts[-2] in (APP_SLICE, SESSION_SLICE)
        and parts[-1].endswith(SERVICE_SUFFIX)
    )
