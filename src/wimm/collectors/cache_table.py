"""Read the disk facts behind the cache table: real paths and sentinels (R12, S5, R15)."""

import os
from collections.abc import Collection, Mapping
from pathlib import Path

from wimm.core.cache_catalog import (
    CacheObservations,
    CacheResolution,
    resolve_cache_paths,
    sentinel_candidates,
)


def _real_path(*, path: Path) -> Path | None:
    """The real path of an existing folder; None when it is missing or cannot be resolved."""
    try:
        return Path(os.path.realpath(path, strict=True))
    except OSError:
        return None


def _observe(*, first: CacheResolution) -> CacheObservations:
    real: dict[Path, Path] = {}
    sentinels: set[Path] = set()
    for cache in first.caches:
        resolved = _real_path(path=cache.path)
        if resolved is None:
            continue
        real[cache.path] = resolved
        if cache.redirected:
            probes = sentinel_candidates(kind=cache.kind, path=resolved)
            sentinels.update(probe for probe in probes if probe.exists())
    return CacheObservations(real=real, sentinels=frozenset(sentinels))


def read_cache_table(
    *, environ: Mapping[str, str], home: Path, roots: Collection[Path]
) -> CacheResolution:
    """Where each cache really is: the candidates, then their real paths and sentinels.

    The collector and the executor both call this, so the type of a folder is decided by its
    place and never by a plan. ``home`` and ``roots`` are resolved here, the resolver wants
    real paths.
    """
    real_home = Path(os.path.realpath(home))
    real_roots = tuple(Path(os.path.realpath(root)) for root in roots)
    first = resolve_cache_paths(environ=environ, home=real_home, roots=real_roots)
    return resolve_cache_paths(
        environ=environ, home=real_home, roots=real_roots, observed=_observe(first=first)
    )
