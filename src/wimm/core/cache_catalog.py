"""Resolve where the user caches of the disk report are (SPECIFICHE 7.6, R12, S5)."""

import os
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from wimm.core.cache_specs import (
    CACHE_COMMANDS,
    CACHE_SPECS,
    CacheBase,
    CacheCommand,
    CacheSpec,
    spec_for,
)
from wimm.model.disk import CacheKind

# A native cleaning command gets only these variables (S6), plus the one that aims it at the
# planned folder: GOFLAGS, YARN_RC_FILENAME, LD_PRELOAD and the like never reach it.
COMMAND_ENV_ALLOWLIST = ("PATH", "HOME", "LANG")
FOLDER_PLACEHOLDER = "{folder}"
PARENT_PLACEHOLDER = "{parent}"

# Cleaned by emptying only these folders under the cache folder: cargo keeps `registry/index`
# and everything else of CARGO_HOME (`bin/`, `config.toml`) out of reach (R14).
CLEAN_SUBDIRS: Mapping[CacheKind, tuple[str, ...]] = {
    CacheKind.CARGO_REGISTRY: ("cache", "src"),
    CacheKind.CARGO_GIT: ("db", "checkouts"),
    # ollama keeps nothing else in its models folder; a redirected one may hold other files.
    CacheKind.OLLAMA: ("blobs", "manifests"),
    # What `sdkmanager` downloads again. `cmdline-tools` (sdkmanager itself) and `licenses`
    # (the accepted ones) stay, or the SDK could not be reinstalled without a manual setup.
    CacheKind.ANDROID_SDK: (
        "system-images",
        "platforms",
        "build-tools",
        "platform-tools",
        "emulator",
        "ndk",
        "cmake",
        "sources",
        ".temp",
    ),
}
# Their files are read-only, so emptying the folder fails halfway: only the tool's own command
# can clean them, and without the tool (`withheld_kinds`) they are measured and never offered.
COMMAND_ONLY_KINDS = frozenset({CacheKind.GO_MOD})

CACHEDIR_TAG = "CACHEDIR.TAG"
XDG_CACHE_VAR = "XDG_CACHE_HOME"
XDG_DEFAULT_RELATIVE = ".cache"
# Folders of the home that no per-tool variable may be, or hold: emptying one would wipe
# the caches of other tools (BUN_INSTALL_CACHE_DIR=~/.cache) or user config.
SHARED_HOME_FOLDERS = (".cache", ".local", ".local/share", ".config")
XDG_DESKTOP_NAMES = frozenset({".cache", "cache"})
MIN_GENERIC_SENTINELS = 2


class CacheAccess(StrEnum):
    CLEANABLE = "cleanable"
    MEASURE_ONLY = "measure_only"


class RejectReason(StrEnum):
    NOT_ABSOLUTE = "not_absolute"  # relative, "~" or a flag value such as "0"
    OUTSIDE_HOME = "outside_home"  # the home itself, an ancestor, or another tree
    ROOT_CONFLICT = "root_conflict"  # a project root, an ancestor of one, or inside one
    COVERS_OTHER_CACHES = "covers_other_caches"  # is, or holds, another cache or a shared folder


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheObservations:
    """Disk facts from the caller.

    ``real`` maps the final candidate path to its real path; a path missing from it has not
    been resolved, which counts as unknown, not as already real. ``sentinels`` are the
    sentinel paths that exist.
    """

    real: Mapping[Path, Path] = field(default_factory=dict)
    sentinels: frozenset[Path] = frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedCache:
    kind: CacheKind
    path: Path
    redirected: bool
    access: CacheAccess


@dataclass(frozen=True, slots=True, kw_only=True)
class RejectedCache:
    """A cache the environment points at but that must not be measured; the caller logs it."""

    kind: CacheKind
    value: str
    reason: RejectReason


@dataclass(frozen=True, slots=True, kw_only=True)
class CacheResolution:
    caches: tuple[ResolvedCache, ...]
    rejected: tuple[RejectedCache, ...]


def withheld_kinds(*, which: Callable[[str], str | None]) -> frozenset[CacheKind]:
    """The command-only caches whose tool is not on PATH: nothing can clean them now."""
    return frozenset(
        kind for kind in COMMAND_ONLY_KINDS if which(CACHE_COMMANDS[kind].argv[0]) is None
    )


def command_argv(*, command: CacheCommand, tool: str, folder: str) -> tuple[str, ...]:
    """The command with ``tool`` (an absolute path) first and the planned folder in place.

    A token is replaced only when it is a whole argument, so a folder name that contains
    ``{parent}`` stays one literal argument.
    """
    values = {FOLDER_PLACEHOLDER: folder, PARENT_PLACEHOLDER: str(Path(folder).parent)}
    return (tool, *(values.get(arg, arg) for arg in command.argv[1:]))


def command_env(
    *, command: CacheCommand, folder: str, environ: Mapping[str, str]
) -> dict[str, str]:
    """The environment of a cleaning command: the allowlist and its own folder variable."""
    env = {name: environ[name] for name in COMMAND_ENV_ALLOWLIST if name in environ}
    if command.env_var is not None:
        env[command.env_var] = folder
    return env


def sentinel_candidates(*, kind: CacheKind, path: Path) -> tuple[Path, ...]:
    """Every path worth probing to tell whether ``path`` is a cache of ``kind``.

    ``CACHEDIR.TAG`` first, then the tool's own files, then its generic entries.
    """
    spec = spec_for(kind=kind)
    names = (CACHEDIR_TAG, *spec.sentinel_files, *spec.sentinel_entries)
    return tuple(path / name for name in names)


def _is_tool_cache(*, spec: CacheSpec, path: Path, found: frozenset[Path]) -> bool:
    """CACHEDIR.TAG, or a file only the tool creates, or at least two of its generic entries."""
    if (path / CACHEDIR_TAG) in found or any((path / n) in found for n in spec.sentinel_files):
        return True
    generic = sum((path / name) in found for name in spec.sentinel_entries)
    return generic >= MIN_GENERIC_SENTINELS


def _refusal(*, path: Path, home: Path, roots: Collection[Path]) -> RejectReason | None:
    if path == home or not path.is_relative_to(home):
        return RejectReason.OUTSIDE_HOME
    for root in roots:
        if path.is_relative_to(root) or root.is_relative_to(path):
            return RejectReason.ROOT_CONFLICT
    return None


def _covers_other_caches(*, spec: CacheSpec, path: Path, home: Path) -> bool:
    """The path is, or is an ancestor of, another cache's usual place or a shared folder."""
    protected = [home / name for name in SHARED_HOME_FOLDERS]
    protected += [_default_path(spec=s, home=home) for s in CACHE_SPECS if s.kind is not spec.kind]
    return any(place == path or place.is_relative_to(path) for place in protected)


def _first_entry(*, value: str, separator: str) -> str:
    return value.split(separator)[0].strip() if separator else value


class _Raw(NamedTuple):
    value: str
    desktop: bool  # under an XDG_CACHE_HOME that looks like a cache folder: no sentinel needed


def _raw_value(*, spec: CacheSpec, environ: Mapping[str, str]) -> _Raw | None:
    """The environment's own answer for this cache, or None when it says nothing."""
    names = (spec.env_var, *spec.env_aliases) if spec.env_var else ()
    for name in names:
        tool = _first_entry(value=environ.get(name, ""), separator=spec.list_separator)
        if tool:
            return _Raw(os.path.join(tool, spec.env_subpath) if spec.env_subpath else tool, False)
    if spec.fallback_var:
        root = _first_entry(value=environ.get(spec.fallback_var, ""), separator=os.pathsep)
        if root:
            return _Raw(os.path.join(root, spec.fallback_subpath), False)
    xdg = environ.get(XDG_CACHE_VAR, "")
    if xdg and spec.base is CacheBase.XDG_CACHE:
        return _Raw(os.path.join(xdg, spec.relative), Path(xdg).name.lower() in XDG_DESKTOP_NAMES)
    return None


def _default_path(*, spec: CacheSpec, home: Path) -> Path:
    if spec.base is CacheBase.XDG_CACHE:
        return home / XDG_DEFAULT_RELATIVE / spec.relative
    return home / spec.relative


def _at_default(
    *, spec: CacheSpec, default: Path, home: Path, scope: tuple[Collection[Path], CacheObservations]
) -> ResolvedCache | RejectedCache:
    """A cache at its usual place; if the caller resolved it elsewhere, it is judged there."""
    roots, observed = scope
    real = observed.real.get(default, default)
    reason = _refusal(path=real, home=home, roots=roots) if real != default else None
    if reason is not None:
        return RejectedCache(kind=spec.kind, value=str(default), reason=reason)
    # A link on the way (the folder or a parent) is never cleaned: what is behind it is not
    # the tool's. The lexical path stays, so the executor can look at the link itself.
    access = CacheAccess.CLEANABLE if real == default else CacheAccess.MEASURE_ONLY
    return ResolvedCache(kind=spec.kind, path=default, redirected=False, access=access)


def _resolve_redirected(
    *, spec: CacheSpec, raw: _Raw, home: Path, scope: tuple[Collection[Path], CacheObservations]
) -> ResolvedCache | RejectedCache:
    roots, observed = scope
    lexical = Path(os.path.normpath(raw.value))
    default = _default_path(spec=spec, home=home)
    if lexical == default:
        return _at_default(spec=spec, default=default, home=home, scope=scope)
    path = observed.real.get(lexical, lexical)
    reason = _refusal(path=path, home=home, roots=roots)
    if reason is None and any(
        _covers_other_caches(spec=spec, path=p, home=home) for p in (lexical, path)
    ):
        reason = RejectReason.COVERS_OTHER_CACHES
    if reason is not None:
        return RejectedCache(kind=spec.kind, value=raw.value, reason=reason)
    resolved = lexical in observed.real
    unlocked = resolved and _is_tool_cache(spec=spec, path=path, found=observed.sentinels)
    trusted = (raw.desktop or unlocked) and path == lexical
    access = CacheAccess.CLEANABLE if trusted else CacheAccess.MEASURE_ONLY
    return ResolvedCache(kind=spec.kind, path=lexical, redirected=True, access=access)


def _resolve_one(
    *,
    spec: CacheSpec,
    environ: Mapping[str, str],
    home: Path,
    scope: tuple[Collection[Path], CacheObservations],
) -> ResolvedCache | RejectedCache:
    raw = _raw_value(spec=spec, environ=environ)
    if raw is None:
        default = _default_path(spec=spec, home=home)
        return _at_default(spec=spec, default=default, home=home, scope=scope)
    if not raw.value.startswith("/"):
        return RejectedCache(kind=spec.kind, value=raw.value, reason=RejectReason.NOT_ABSOLUTE)
    return _resolve_redirected(spec=spec, raw=raw, home=home, scope=scope)


def resolve_cache_paths(
    *,
    environ: Mapping[str, str],
    home: Path,
    roots: Collection[Path],
    observed: CacheObservations | None = None,
) -> CacheResolution:
    """Where each cache is, given the environment (R12, S5). Pure.

    Disk facts arrive in ``observed``: call once without them to learn the candidates, then
    again with their real paths (keyed by the candidate path) and sentinels. ``home`` and
    ``roots`` must be real paths. A folder at its default place is ``CLEANABLE``, unless the
    caller resolved it elsewhere and that place is outside ``home`` or related to a root.
    A redirected one is dropped into ``rejected`` unless strictly inside ``home`` and
    unrelated to every root (equal, ancestor, inside): ``GOCACHE=$HOME`` must not turn the
    home into a "cache". One that passes is ``CLEANABLE`` only when its real path was
    resolved and it shows ``CACHEDIR.TAG``, a file specific to the tool or two of its
    generic entries; otherwise ``MEASURE_ONLY``. A folder placed by ``XDG_CACHE_HOME`` takes the
    same safety checks but needs no sentinel: it is a desktop standard, not a tool's redirect.
    """
    scope = (roots, observed or CacheObservations())
    kept: list[ResolvedCache] = []
    rejected: list[RejectedCache] = []
    for spec in CACHE_SPECS:
        outcome = _resolve_one(spec=spec, environ=environ, home=home, scope=scope)
        if isinstance(outcome, ResolvedCache):
            kept.append(outcome)
        else:
            rejected.append(outcome)
    return CacheResolution(caches=tuple(kept), rejected=tuple(rejected))
