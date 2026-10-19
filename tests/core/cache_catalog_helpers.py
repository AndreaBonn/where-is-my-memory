from pathlib import Path

from wimm.core.cache_catalog import (
    CacheObservations,
    ResolvedCache,
    resolve_cache_paths,
    sentinel_candidates,
)
from wimm.model.disk import CacheKind

# --- resolve_cache_paths (R12, S5) ---------------------------------------------------

HOME = Path("/home/u")


ROOT = Path("/home/u/projects")


ROOTS = (ROOT,)


def _paths(
    *, environ: dict[str, str], observed: CacheObservations | None = None
) -> dict[str, Path]:
    result = resolve_cache_paths(
        environ=environ, home=HOME, roots=ROOTS, observed=observed or CacheObservations()
    )
    return {entry.kind.value: entry.path for entry in result.caches}


def _resolved(
    *, environ: dict[str, str], observed: CacheObservations | None = None
) -> dict[str, ResolvedCache]:
    result = resolve_cache_paths(
        environ=environ, home=HOME, roots=ROOTS, observed=observed or CacheObservations()
    )
    return {entry.kind.value: entry for entry in result.caches}


def _sentinel(kind: CacheKind, path: Path) -> CacheObservations:
    sentinel = sentinel_candidates(kind=kind, path=path)[0]
    return CacheObservations(real={path: path}, sentinels=frozenset({sentinel}))
