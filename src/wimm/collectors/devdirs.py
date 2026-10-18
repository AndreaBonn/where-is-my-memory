import logging
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wimm.collectors.devdir_context import read_devdir_context
from wimm.collectors.dirsize import measure_dir_size
from wimm.core.constants import (
    DEVDIR_SOURCE_DIRNAME,
    DIRSIZE_PAUSE_EVERY,
    DIRSIZE_PAUSE_S,
    DIRSIZE_YIELD_EVERY,
    SECONDS_PER_DAY,
)
from wimm.core.devdir_rules import MARKERS_BY_NAME, classify_devdir, rebuild_marker
from wimm.model.disk import DevDir

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DevDirSettings:
    """Where and how deep to search. Depth: root = 0, its children = 1."""

    roots: tuple[Path, ...]
    home: Path
    max_depth: int


@dataclass(frozen=True)
class DevDirScan:
    """All candidates found (age filtering happens in core) and unreadable entries skipped."""

    devdirs: tuple[DevDir, ...]
    error_count: int


class _Walker:
    def __init__(self, max_depth: int, sleep: Callable[[float], None], home: Path) -> None:
        self._max_depth = max_depth
        self._sleep = sleep
        self._home = home
        self._entries = 0
        self.errors = 0
        # Keyed by path: nested or repeated roots reach the same folder twice.
        self.found: dict[Path, str] = {}

    def tick(self) -> None:
        self._entries += 1
        if self._entries % DIRSIZE_PAUSE_EVERY == 0:
            self._sleep(DIRSIZE_PAUSE_S)
        elif self._entries % DIRSIZE_YIELD_EVERY == 0:
            self._sleep(0)

    def walk(self, root: Path) -> None:
        pending = [(root, 0)]
        while pending:
            directory, depth = pending.pop()
            for child in self._subdirectories(directory=directory):
                self._classify(child=child, depth=depth + 1, pending=pending)

    def _classify(self, child: Path, depth: int, pending: list[tuple[Path, int]]) -> None:
        # Hidden folders are skipped, except the hidden names of the table (a refused one
        # is still not entered); a folder that was found is not entered either.
        marker = self._devdir_marker(path=child)
        if marker is not None:
            self.found[child] = marker
        elif depth < self._max_depth and not child.name.startswith("."):
            pending.append((child, depth))

    def _devdir_marker(self, path: Path) -> str | None:
        """Return the rebuild marker of a dependency folder, ``None`` when it is not one."""
        if path.name not in MARKERS_BY_NAME:
            return None
        try:
            context = read_devdir_context(path=path, home=self._home)
        except OSError:
            self.errors += 1
            return None
        if not classify_devdir(name=path.name, context=context):
            return None
        return rebuild_marker(name=path.name, parent_entries=context.parent_entries)

    def _subdirectories(self, directory: Path) -> list[Path]:
        children: list[Path] = []
        try:
            iterator = os.scandir(directory)
        except OSError:
            self.errors += 1
            return children
        with iterator:
            while True:
                try:
                    entry = next(iterator, None)
                except OSError:
                    self.errors += 1
                    break
                if entry is None:
                    break
                self.tick()
                if self._is_real_directory(entry=entry):
                    children.append(Path(entry.path))
        return children

    def _is_real_directory(self, entry: os.DirEntry[str]) -> bool:
        try:
            return entry.is_dir(follow_symlinks=False)
        except OSError:
            self.errors += 1
            return False

    def measure(self, path: Path, cache_dir: Path) -> int:
        result = measure_dir_size(root=path, cache_dir=cache_dir, sleep=self._sleep)
        self.errors += result.error_count
        return result.size_bytes

    def newest_mtime(self, project: Path) -> float:
        """Newest mtime in the project first level and in ``src/`` first level.

        Dependency and build-output folders are not the user's edits, so no name of the
        table counts, found or not: a freshly rebuilt ``target`` must not make a project recent.
        """
        newest = self._newest_in(directory=project, skip=frozenset(MARKERS_BY_NAME))
        source = project / DEVDIR_SOURCE_DIRNAME
        if _is_real_dir(path=source):
            newest = max(newest, self._newest_in(directory=source, skip=frozenset()))
        if newest > 0:
            return newest
        try:
            return os.lstat(project).st_mtime
        except OSError:
            self.errors += 1
            return 0.0

    def _newest_in(self, directory: Path, skip: frozenset[str]) -> float:
        newest = 0.0
        try:
            iterator = os.scandir(directory)
        except FileNotFoundError:
            return newest
        except OSError:
            self.errors += 1
            return newest
        with iterator:
            while True:
                try:
                    entry = next(iterator, None)
                except OSError:
                    self.errors += 1
                    break
                if entry is None:
                    break
                self.tick()
                if entry.name not in skip:
                    newest = max(newest, self._entry_mtime(entry=entry))
        return newest

    def _entry_mtime(self, entry: os.DirEntry[str]) -> float:
        try:
            return entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            self.errors += 1
            return 0.0


def project_age_days(*, project: Path, now: float) -> int | None:
    """Whole days since ``project`` was last touched, by the scan's rule (SPECIFICHE 7.6).

    The newest mtime among the first-level entries (dependency folders excluded) and the
    first level of a real ``src/``; never negative. ``None`` if any of it could not be read:
    an age computed on a partial view could hide a recent edit.
    """
    walker = _Walker(max_depth=0, sleep=time.sleep, home=Path.home())
    newest = walker.newest_mtime(project=project)
    if walker.errors:
        return None
    return max(0, int((now - newest) // SECONDS_PER_DAY))


def _is_real_dir(path: Path) -> bool:
    """A directory that is not a symlink; a missing path is simply not one."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_usable_root(root: Path) -> bool:
    """A real directory now. Whether it may be a root is ADR-007's verdict, given by the caller."""
    try:
        return stat.S_ISDIR(os.lstat(root).st_mode)
    except OSError:
        return False


def _build_devdir(path: Path, walker: _Walker, cache_dir: Path, now: float) -> DevDir | None:
    try:
        info = os.lstat(path)
    except OSError:
        walker.errors += 1
        return None
    if not stat.S_ISDIR(info.st_mode):
        # Replaced by a symlink or a file since the walk: measuring it would follow it.
        return None
    newest = walker.newest_mtime(project=path.parent)
    age_days = max(0, int((now - newest) // SECONDS_PER_DAY))
    size = walker.measure(path=path, cache_dir=cache_dir)
    return DevDir(
        path=str(path),
        size=size,
        age_days=age_days,
        st_ino=info.st_ino,
        st_dev=info.st_dev,
        marker=walker.found.get(path, ""),
    )


def scan_devdirs(
    settings: DevDirSettings,
    cache_dir: Path,
    now: float,
    sleep: Callable[[float], None] = time.sleep,
) -> DevDirScan:
    """Find rebuildable dependency folders under the admitted roots (SPECIFICHE 7.6).
    ``settings.roots`` are the roots ADR-007 admits (``Config.admitted_roots``).

    A folder qualifies by ``classify_devdir`` (name, sibling marker, second signal; never
    a project directly in the home). Symlinks are never followed, hidden folders are
    skipped except the hidden names of that table, and the search does not descend into a
    folder found. A folder at depth ``max_depth`` is found, one deeper is not. ``age_days``
    is the whole number of days between ``now`` (epoch seconds) and the newest mtime among the
    parent project's first-level entries (the found folder excluded) and the
    first level of its ``src/``; an empty project falls back to its own mtime.
    Unreadable entries are skipped and counted, never raised.
    """
    walker = _Walker(max_depth=settings.max_depth, sleep=sleep, home=settings.home)
    for root in settings.roots:
        if _is_usable_root(root=root):
            walker.walk(root=root)
        else:
            LOGGER.info("Skipping devdirs root %s: missing or not a real directory", root)
    built = (
        _build_devdir(path=path, walker=walker, cache_dir=cache_dir, now=now)
        for path in walker.found
    )
    devdirs = tuple(item for item in built if item is not None)
    return DevDirScan(devdirs=devdirs, error_count=walker.errors)
