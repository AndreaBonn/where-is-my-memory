import json
import logging
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wimm.core.constants import (
    DIRSIZE_PAUSE_EVERY,
    DIRSIZE_PAUSE_S,
    DIRSIZE_YIELD_EVERY,
    DISK_CACHE_FILENAME,
    DISK_CACHE_VERSION,
)
from wimm.paths import ensure_private_dir, write_private_atomic

LOGGER = logging.getLogger(__name__)
BLOCK_BYTES = 512


@dataclass(frozen=True)
class DirSize:
    """Result of a directory size measurement.

    Attributes
    ----------
    size_bytes : int
        Disk space occupied (st_blocks * 512), not the apparent size.
    error_count : int
        Entries skipped because they vanished or could not be read.
    from_cache : bool
        True when the value came from disk-cache.json without rescanning.
    """

    size_bytes: int
    error_count: int
    from_cache: bool


def pace(*, count: int, sleep: Callable[[float], None]) -> None:
    """Yield the GIL every 1,000 entries and pause 10 ms every 10,000."""
    if count % DIRSIZE_PAUSE_EVERY == 0:
        sleep(DIRSIZE_PAUSE_S)
    elif count % DIRSIZE_YIELD_EVERY == 0:
        sleep(0)


class _Scanner:
    def __init__(self, sleep: Callable[[float], None]) -> None:
        self._sleep = sleep
        self._seen: set[tuple[int, int]] = set()
        self._entries = 0
        self.size = 0
        self.errors = 0

    def _tick(self) -> None:
        self._entries += 1
        pace(count=self._entries, sleep=self._sleep)

    def _account(self, info: os.stat_result) -> None:
        # Directories always have st_nlink > 1 but cannot be hard linked.
        if info.st_nlink > 1 and not stat.S_ISDIR(info.st_mode):
            key = (info.st_dev, info.st_ino)
            if key in self._seen:
                return
            self._seen.add(key)
        self.size += info.st_blocks * BLOCK_BYTES

    def run(self, root: Path) -> None:
        try:
            self._account(os.lstat(root))
        except OSError:
            self.errors += 1
            return
        pending = [root]
        while pending:
            self._scan_directory(directory=pending.pop(), pending=pending)

    def _scan_directory(self, directory: Path, pending: list[Path]) -> None:
        try:
            iterator = os.scandir(directory)
        except OSError:
            self.errors += 1
            return
        with iterator:
            while True:
                try:
                    entry = next(iterator, None)
                except OSError:
                    self.errors += 1
                    return
                if entry is None:
                    return
                self._visit(entry=entry, pending=pending)

    def _visit(self, entry: os.DirEntry[str], pending: list[Path]) -> None:
        self._tick()
        try:
            if entry.is_symlink():
                return
            info = entry.stat(follow_symlinks=False)
            self._account(info)
            if entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
        except OSError:
            self.errors += 1


def _cache_key(root: Path, info: os.stat_result) -> str:
    return f"{os.path.realpath(root)}|{info.st_dev}|{info.st_ino}"


def _load_entries(cache_file: Path) -> dict[str, Any]:
    try:
        raw = cache_file.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as error:
        LOGGER.warning("Cannot read size cache %s: %s", cache_file, error)
        return {}
    try:
        document = json.loads(raw)
        entries = document["entries"]
        if document["version"] != DISK_CACHE_VERSION or not isinstance(entries, dict):
            raise ValueError("unexpected cache layout")
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        LOGGER.warning("Ignoring corrupt size cache %s: %s", cache_file, error)
        return {}
    return entries


def _store_entries(cache_dir: Path, entries: dict[str, Any]) -> None:
    document = {"version": DISK_CACHE_VERSION, "entries": entries}
    try:
        ensure_private_dir(path=cache_dir)
        write_private_atomic(
            path=cache_dir / DISK_CACHE_FILENAME,
            data=json.dumps(document, sort_keys=True).encode(),
        )
    except (OSError, ValueError) as error:
        LOGGER.warning("Cannot write size cache in %s: %s", cache_dir, error)


def _cached_result(entry: object, mtime_ns: int) -> DirSize | None:
    if not isinstance(entry, dict) or entry.get("mtime_ns") != mtime_ns:
        return None
    size, errors = entry.get("size"), entry.get("errors")
    if not isinstance(size, int) or not isinstance(errors, int):
        return None
    return DirSize(size_bytes=size, error_count=errors, from_cache=True)


def _entry_for(result: DirSize, mtime_ns: int) -> dict[str, int]:
    return {"size": result.size_bytes, "errors": result.error_count, "mtime_ns": mtime_ns}


def _scan(root: Path, sleep: Callable[[float], None]) -> DirSize:
    scanner = _Scanner(sleep=sleep)
    scanner.run(root=root)
    return DirSize(size_bytes=scanner.size, error_count=scanner.errors, from_cache=False)


def measure_dir_size(
    *, root: Path, cache_dir: Path, sleep: Callable[[float], None] = time.sleep
) -> DirSize:
    """Measure the on-disk size of a directory tree (SPECIFICHE 7.6.1).

    Symlinks are neither followed nor counted, hard links count once per
    (st_dev, st_ino), and vanished or unreadable entries are skipped and
    counted in ``error_count``; nothing is raised for them. ``sleep`` yields
    the GIL every 1,000 entries and pauses 10 ms every 10,000.

    Notes
    -----
    Cache key: real path + st_dev + st_ino, valid while the root mtime is
    unchanged (edits deeper in the tree stay invisible, as 7.6.1 accepts). A
    symlinked root is resolved first; results with errors are not cached; mount
    points are crossed, like ``du``. Not thread-safe: callers serialise calls.
    """
    root = Path(os.path.realpath(root))
    try:
        info = os.lstat(root)
    except OSError:
        return DirSize(size_bytes=0, error_count=1, from_cache=False)
    return _measure_cached(root=root, info=info, cache_dir=cache_dir, sleep=sleep)


def _measure_cached(
    *, root: Path, info: os.stat_result, cache_dir: Path, sleep: Callable[[float], None]
) -> DirSize:
    key = _cache_key(root=root, info=info)
    entries = _load_entries(cache_file=cache_dir / DISK_CACHE_FILENAME)
    cached = _cached_result(entry=entries.get(key), mtime_ns=info.st_mtime_ns)
    if cached is not None:
        return cached
    result = _scan(root=root, sleep=sleep)
    if result.error_count:
        return result
    entries[key] = _entry_for(result=result, mtime_ns=info.st_mtime_ns)
    _store_entries(cache_dir=cache_dir, entries=entries)
    return result
