"""Tree removal that stays on one filesystem and never follows a link (SPECIFICHE 8.2, S2).

Every step works through an open directory descriptor with ``O_NOFOLLOW``: a path swapped
for a symlink between the check and the removal is refused by the kernel, not by us.
A subdirectory on another device, or listed as a mount point, is skipped and recorded:
its content is never touched.
"""

import errno
import logging
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from wimm.core.constants import MAX_RECORDED_REMOVAL_ERRORS, MOUNTINFO_PATH
from wimm.model.actions import DirFingerprint

from .errors import TargetChanged

LOGGER = logging.getLogger(__name__)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
BLOCK_BYTES = 512
MOUNTINFO_MOUNTPOINT_FIELD = 4
OCTAL_ESCAPE_LENGTH = 4


@dataclass(frozen=True, slots=True)
class TreeRemoval:
    """What a removal did. `freed_bytes` is the allocated size (`st_blocks * 512`) of the
    removed entries that had no other hard link: a measure, not the daemon's accounting."""

    removed: int = 0
    freed_bytes: int = 0
    error_count: int = 0
    error_samples: tuple[str, ...] = ()
    skipped_mounts: tuple[str, ...] = ()
    root_removed: bool = False

    @property
    def remaining(self) -> int:
        """Entries known to be left: failed removals plus skipped mounts."""
        return self.error_count + len(self.skipped_mounts)

    def __add__(self, other: "TreeRemoval") -> "TreeRemoval":
        samples = (*self.error_samples, *other.error_samples)
        return TreeRemoval(
            removed=self.removed + other.removed,
            freed_bytes=self.freed_bytes + other.freed_bytes,
            error_count=self.error_count + other.error_count,
            error_samples=samples[:MAX_RECORDED_REMOVAL_ERRORS],
            skipped_mounts=(*self.skipped_mounts, *other.skipped_mounts),
            root_removed=self.root_removed or other.root_removed,
        )


def parse_mountinfo(*, text: str) -> frozenset[str]:
    """Mount points listed in the text of ``/proc/self/mountinfo`` (octal escapes decoded)."""
    points = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) > MOUNTINFO_MOUNTPOINT_FIELD:
            points.add(_unescape(text=fields[MOUNTINFO_MOUNTPOINT_FIELD]))
    return frozenset(points)


def _unescape(*, text: str) -> str:
    out = []
    index = 0
    while index < len(text):
        chunk = text[index : index + OCTAL_ESCAPE_LENGTH]
        if chunk.startswith("\\") and len(chunk) == OCTAL_ESCAPE_LENGTH and chunk[1:].isdigit():
            out.append(chr(int(chunk[1:], 8)))
            index += OCTAL_ESCAPE_LENGTH
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def read_mountpoints() -> frozenset[str]:
    """The current mount points; empty (with a warning) if the table cannot be read.

    The device check still protects a mount on another filesystem; the table adds the
    bind mounts, which share the device of the directory they sit in.
    """
    try:
        with open(MOUNTINFO_PATH, encoding="utf-8") as table:
            return parse_mountinfo(text=table.read())
    except OSError as error:
        LOGGER.warning(
            "Cannot read %s, only the device check protects mounts: %s", MOUNTINFO_PATH, error
        )
        return frozenset()


class _Removal:
    """One walk. Counters are plain attributes: the walk is single-threaded."""

    def __init__(self, *, root_dev: int, mountpoints: frozenset[str]) -> None:
        self._root_dev = root_dev
        self._mountpoints = mountpoints
        self.result = TreeRemoval()

    def record_error(self, *, path: str, error: OSError) -> None:
        sample = (f"{path}: {error.strerror or error}",)
        self.result += TreeRemoval(error_count=1, error_samples=sample)

    def _record_removed(self, *, info: os.stat_result) -> None:
        freed = info.st_blocks * BLOCK_BYTES if info.st_nlink == 1 else 0
        self.result += TreeRemoval(removed=1, freed_bytes=freed)

    def empty(self, *, dir_fd: int, path: str) -> bool:
        """Remove what is inside the directory open at `dir_fd`; True if nothing is left."""
        try:
            with os.scandir(dir_fd) as iterator:
                entries = list(iterator)
        except OSError as error:
            self.record_error(path=path, error=error)
            return False
        clean = True
        for entry in entries:
            if not self._remove_entry(dir_fd=dir_fd, entry=entry, path=f"{path}/{entry.name}"):
                clean = False
        return clean

    def _remove_entry(self, *, dir_fd: int, entry: os.DirEntry[str], path: str) -> bool:
        try:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                return self._remove_subdirectory(
                    dir_fd=dir_fd, name=entry.name, path=path, info=info
                )
            os.unlink(entry.name, dir_fd=dir_fd)
        except FileNotFoundError:
            return True
        except OSError as error:
            self.record_error(path=path, error=error)
            return False
        self._record_removed(info=info)
        return True

    def skip_mount(self, *, dev: int, path: str) -> bool:
        """True (and recorded) if `path` is on another device or listed as a mount point."""
        if dev == self._root_dev and path not in self._mountpoints:
            return False
        LOGGER.warning("Skipping mount point %s: not removing across mounts", path)
        self.result += TreeRemoval(skipped_mounts=(path,))
        return True

    def _remove_subdirectory(
        self, *, dir_fd: int, name: str, path: str, info: os.stat_result
    ) -> bool:
        if self.skip_mount(dev=info.st_dev, path=path):
            return False
        child = os.open(name, DIR_FLAGS, dir_fd=dir_fd)
        try:
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise OSError(errno.ESTALE, "directory replaced during removal")
            clean = self.empty(dir_fd=child, path=path)
        finally:
            os.close(child)
        if clean:
            os.rmdir(name, dir_fd=dir_fd)
            self._record_removed(info=info)
        return clean


def _device_of(*, fd: int) -> int:
    return os.fstat(fd).st_dev


def _refuse_mounted_root(
    *, fingerprint: DirFingerprint, mountpoints: frozenset[str], parent_fd: int
) -> None:
    """A root that is a mount (own device or listed) would have its content emptied: refuse."""
    if fingerprint.realpath in mountpoints or _device_of(fd=parent_fd) != fingerprint.st_dev:
        raise TargetChanged(f"{fingerprint.realpath} is a mount point, nothing was touched")


def _open_checked(*, name: str, fingerprint: DirFingerprint, dir_fd: int | None = None) -> int:
    """Open a directory without following a link; refuse one that is not the planned inode."""
    fd = os.open(name, DIR_FLAGS, dir_fd=dir_fd)
    info = os.fstat(fd)
    if (info.st_ino, info.st_dev) != (fingerprint.st_ino, fingerprint.st_dev):
        os.close(fd)
        raise TargetChanged(f"{fingerprint.realpath} is no longer the folder the plan showed")
    return fd


def empty_directory(
    *,
    fingerprint: DirFingerprint,
    subdirs: Iterable[str] = (),
    mountpoints: frozenset[str] = frozenset(),
    root_dev: int | None = None,
) -> TreeRemoval:
    """Remove the content of the planned folder, or of its `subdirs` that exist, keeping them.

    `root_dev` is the device the walk must stay on (default: the folder's own). A folder that
    is itself a mount is refused with `TargetChanged`.
    """
    parent = os.open(Path(fingerprint.realpath).parent, DIR_FLAGS)
    try:
        _refuse_mounted_root(fingerprint=fingerprint, mountpoints=mountpoints, parent_fd=parent)
    finally:
        os.close(parent)
    root = _open_checked(name=fingerprint.realpath, fingerprint=fingerprint)
    try:
        walk = _Removal(root_dev=root_dev or fingerprint.st_dev, mountpoints=mountpoints)
        for name in tuple(subdirs) or (None,):
            _empty_one(walk=walk, root=root, base=fingerprint.realpath, name=name)
        return walk.result
    finally:
        os.close(root)


def _empty_one(*, walk: _Removal, root: int, base: str, name: str | None) -> None:
    if name is None:
        walk.empty(dir_fd=root, path=base)
        return
    try:
        child = os.open(name, DIR_FLAGS, dir_fd=root)
    except FileNotFoundError:
        return
    except OSError as error:
        walk.record_error(path=f"{base}/{name}", error=error)
        return
    try:
        path = f"{base}/{name}"
        if not walk.skip_mount(dev=os.fstat(child).st_dev, path=path):
            walk.empty(dir_fd=child, path=path)
    finally:
        os.close(child)


def remove_directory(
    *, fingerprint: DirFingerprint, mountpoints: frozenset[str] = frozenset()
) -> TreeRemoval:
    """Remove the planned folder and everything in it; `root_removed` tells if it is gone."""
    path = Path(fingerprint.realpath)
    parent = os.open(path.parent, DIR_FLAGS)
    try:
        _refuse_mounted_root(fingerprint=fingerprint, mountpoints=mountpoints, parent_fd=parent)
        child = _open_checked(name=path.name, fingerprint=fingerprint, dir_fd=parent)
        try:
            walk = _Removal(root_dev=fingerprint.st_dev, mountpoints=mountpoints)
            clean = walk.empty(dir_fd=child, path=fingerprint.realpath)
        finally:
            os.close(child)
        if not clean:
            return walk.result
        try:
            os.rmdir(path.name, dir_fd=parent)
        except OSError as error:
            walk.record_error(path=fingerprint.realpath, error=error)
            return walk.result
        return walk.result + TreeRemoval(root_removed=True)
    finally:
        os.close(parent)


def _open_parents(*, root: str, parts: list[str]) -> int:
    fd = os.open(root, DIR_FLAGS)
    try:
        for part in parts:
            try:
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise TargetChanged(f"{part} is not a plain directory under {root}") from error
                raise
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def remove_file(*, root: str, relative: str, st_ino: int, st_dev: int) -> TreeRemoval:
    """Unlink one planned file below `root`, following no link: else `TargetChanged`.

    A missing file raises `FileNotFoundError`."""
    *parents, name = relative.split("/")
    if any(part in ("", "..", ".") for part in (*parents, name)):
        raise TargetChanged(f"{relative} is not a path inside {root}")
    parent = _open_parents(root=root, parts=parents)
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_ino, info.st_dev) != (st_ino, st_dev):
            raise TargetChanged(f"{relative} is not the file the plan showed")
        os.unlink(name, dir_fd=parent)
    finally:
        os.close(parent)
    freed = info.st_blocks * BLOCK_BYTES if info.st_nlink == 1 else 0
    return TreeRemoval(removed=1, freed_bytes=freed)
