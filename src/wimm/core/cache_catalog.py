"""Resolve where the user caches of the disk report are (SPECIFICHE 7.6, R12, S5)."""

import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from wimm.core.cache_specs import CACHE_SPECS, CacheBase, CacheSpec, spec_for
from wimm.model.disk import CacheKind

# Legacy list (cache folders relative to HOME, keyed by CacheKind.value), kept until the
# collector and the executor move to the resolved table (T032, T033).
CACHE_RELATIVE_PATHS = (
    ("uv", ".cache/uv"),
    ("npm", ".npm/_cacache"),
    ("pip", ".cache/pip"),
    ("trash", ".local/share/Trash"),
    ("thumbnails", ".cache/thumbnails"),
)
# Variables that redirect a cache tool away from the planned folder: removed from its environment.
CACHE_ENV_VARS = ("UV_CACHE_DIR", "PIP_CACHE_DIR", "npm_config_cache")

CACHEDIR_TAG = "CACHEDIR.TAG"
XDG_CACHE_VAR = "XDG_CACHE_HOME"
XDG_DEFAULT_RELATIVE = ".cache"
MIN_GENERIC_SENTINELS = 2


class CacheAccess(StrEnum):
    CLEANABLE = "cleanable"
    MEASURE_ONLY = "measure_only"


class RejectReason(StrEnum):
    NOT_ABSOLUTE = "not_absolute"  # relative, "~" or a flag value such as "0"
    OUTSIDE_HOME = "outside_home"  # the home itself, an ancestor, or another tree
    ROOT_CONFLICT = "root_conflict"  # a project root, an ancestor of one, or inside one


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


def _first_entry(*, value: str, separator: str) -> str:
    return value.split(separator)[0].strip() if separator else value


def _raw_value(*, spec: CacheSpec, environ: Mapping[str, str]) -> str | None:
    """The environment's own answer for this cache, or None when it says nothing."""
    names = (spec.env_var, *spec.env_aliases) if spec.env_var else ()
    for name in names:
        tool = _first_entry(value=environ.get(name, ""), separator=spec.list_separator)
        if tool:
            return os.path.join(tool, spec.env_subpath) if spec.env_subpath else tool
    if spec.fallback_var:
        root = _first_entry(value=environ.get(spec.fallback_var, ""), separator=os.pathsep)
        if root:
            return os.path.join(root, spec.fallback_subpath)
    xdg = environ.get(XDG_CACHE_VAR, "")
    if xdg and spec.base is CacheBase.XDG_CACHE:
        return os.path.join(xdg, spec.relative)
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
    path = observed.real.get(default, default)
    reason = _refusal(path=path, home=home, roots=roots) if path != default else None
    if reason is not None:
        return RejectedCache(kind=spec.kind, value=str(default), reason=reason)
    return ResolvedCache(kind=spec.kind, path=path, redirected=False, access=CacheAccess.CLEANABLE)


def _resolve_redirected(
    *, spec: CacheSpec, raw: str, home: Path, scope: tuple[Collection[Path], CacheObservations]
) -> ResolvedCache | RejectedCache:
    roots, observed = scope
    lexical = Path(os.path.normpath(raw))
    default = _default_path(spec=spec, home=home)
    if lexical == default:
        return _at_default(spec=spec, default=default, home=home, scope=scope)
    path = observed.real.get(lexical, lexical)
    reason = _refusal(path=path, home=home, roots=roots)
    if reason is not None:
        return RejectedCache(kind=spec.kind, value=raw, reason=reason)
    resolved = lexical in observed.real
    unlocked = resolved and _is_tool_cache(spec=spec, path=path, found=observed.sentinels)
    access = CacheAccess.CLEANABLE if unlocked else CacheAccess.MEASURE_ONLY
    return ResolvedCache(kind=spec.kind, path=path, redirected=True, access=access)


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
    if not raw.startswith("/"):
        return RejectedCache(kind=spec.kind, value=raw, reason=RejectReason.NOT_ABSOLUTE)
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
    generic entries; otherwise ``MEASURE_ONLY``.
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
