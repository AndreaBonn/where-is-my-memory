import logging
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path

from wimm.collectors.cache_items import ITEM_KINDS, TEXT_PREFIXES, list_tree
from wimm.collectors.dirsize import measure_dir_size
from wimm.core.cache_catalog import CacheAccess, CacheResolution
from wimm.core.cache_items import items_for
from wimm.model.cache_items import CacheItem, CacheRest
from wimm.model.disk import CacheEntry, CacheKind

LOGGER = logging.getLogger(__name__)


def _split_items(
    *, kind: CacheKind, folder: Path, sleep: Callable[[float], None]
) -> tuple[int, tuple[CacheItem, ...], CacheRest]:
    """Size, items and rest of an item kind from ONE fresh walk; none when items cannot fit."""
    listing = list_tree(root=folder, sleep=sleep, text_prefix=TEXT_PREFIXES.get(kind, ""))
    size = listing.disk_bytes
    items, rest = items_for(kind=kind, listing=listing, size=size)
    if sum(item.size for item in items) + rest.shared > size:
        LOGGER.warning("Items of cache %s exceed its measured size %d: dropped", folder, size)
        return size, (), CacheRest()
    return size, items, rest


def _itemized_entry(
    *, kind: CacheKind, folder: Path, info: os.stat_result, sleep: Callable[[float], None]
) -> CacheEntry | None:
    """The entry of an item kind, or None when its tree cannot be split (caller falls back)."""
    try:
        size, items, rest = _split_items(kind=kind, folder=folder, sleep=sleep)
        return CacheEntry(
            kind=kind,
            path=str(folder),
            size=size,
            st_ino=info.st_ino,
            st_dev=info.st_dev,
            items=items,
            rest=rest,
        )
    except ValueError as error:
        LOGGER.warning(
            "Cannot split cache %s into items, showing it whole: %s", folder, error, exc_info=True
        )
        return None


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
    if kind in ITEM_KINDS:
        entry = _itemized_entry(kind=kind, folder=folder, info=info, sleep=sleep)
        if entry is not None:
            return entry
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
