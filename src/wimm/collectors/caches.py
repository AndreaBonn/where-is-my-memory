import logging
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path

from wimm.collectors.dirsize import measure_dir_size
from wimm.core.cache_catalog import CacheAccess, CacheResolution
from wimm.model.disk import CacheEntry, CacheKind

LOGGER = logging.getLogger(__name__)


def _measure_cache(
    kind: CacheKind, folder: Path, cache_dir: Path, sleep: Callable[[float], None]
) -> CacheEntry | None:
    try:
        info = os.lstat(folder)
    except FileNotFoundError:
        return None
    except OSError as error:
        LOGGER.warning("Cannot stat cache %s: %s", folder, error)
        return None
    if not stat.S_ISDIR(info.st_mode):
        LOGGER.debug("Skipping %s: not a real directory", folder)
        return None
    size = measure_dir_size(root=folder, cache_dir=cache_dir, sleep=sleep)
    if size.error_count:
        LOGGER.info("Cache %s measured with %d unreadable entries", folder, size.error_count)
    return CacheEntry(
        kind=kind,
        path=str(folder),
        size=size.size_bytes,
        st_ino=info.st_ino,
        st_dev=info.st_dev,
    )


def collect_caches(
    table: CacheResolution, cache_dir: Path, sleep: Callable[[float], None] = time.sleep
) -> tuple[CacheEntry, ...]:
    """Measure the user caches of the resolved ``table`` (SPECIFICHE 7.6, R12).

    A missing folder gives no entry; a symlink or a non-directory is skipped without being
    followed. A redirected folder that shows nothing of its tool is not reported: the report
    has no way to say "measure only", and the executor would refuse to clean it.
    ``st_ino``/``st_dev`` are the lstat fingerprint of the folder itself, revalidated later by
    the executor. Measurement only: cleaning belongs to the executor.
    """
    entries = (
        _measure_cache(kind=cache.kind, folder=cache.path, cache_dir=cache_dir, sleep=sleep)
        for cache in table.caches
        if cache.access is CacheAccess.CLEANABLE
    )
    return tuple(entry for entry in entries if entry is not None)
