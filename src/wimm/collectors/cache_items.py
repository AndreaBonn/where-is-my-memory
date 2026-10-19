import errno
import logging
import os
import stat
from collections.abc import Callable
from pathlib import Path

from wimm.collectors.dirsize import pace
from wimm.core.cache_items import EntryType, TreeEntry, TreeListing
from wimm.model.disk import CacheKind

LOGGER = logging.getLogger(__name__)

# Kinds whose tree is read a second time to split them into items; must match `items_for`.
ITEM_KINDS = frozenset(
    {
        CacheKind.HUGGINGFACE,
        CacheKind.ANDROID_SDK,
        CacheKind.ANDROID_AVD,
        CacheKind.PLAYWRIGHT,
        CacheKind.JETBRAINS,
    }
)
BLOCK_BYTES = 512
# Never follows a link at open time: a directory swapped for a symlink after its lstat fails.
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
OUT_OF_DESCRIPTORS = frozenset({errno.EMFILE, errno.ENFILE})

Frame = tuple[int, str, list[str]]


def _entry_for(*, name: str, relative: str, info: os.stat_result, fd: int) -> TreeEntry | None:
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        target = os.readlink(name, dir_fd=fd)
        return TreeEntry(path=relative, type=EntryType.SYMLINK, target=target)
    if stat.S_ISDIR(mode):
        return TreeEntry(path=relative, type=EntryType.DIR, st_ino=info.st_ino, st_dev=info.st_dev)
    if not stat.S_ISREG(mode):
        return None
    return TreeEntry(
        path=relative,
        type=EntryType.FILE,
        size=info.st_blocks * BLOCK_BYTES,
        st_ino=info.st_ino,
        st_dev=info.st_dev,
    )


class _Walk:
    """One pass over a tree through directory descriptors: the entries and the disk bytes."""

    def __init__(self, *, sleep: Callable[[float], None]) -> None:
        self._sleep = sleep
        self._seen: set[tuple[int, int]] = set()
        self._count = 0
        self.entries: list[TreeEntry] = []
        self.disk_bytes = 0
        self.skipped = 0

    def _account(self, info: os.stat_result) -> None:
        # Same rule as `dirsize`: a hard-linked file counts once, symlinks never count.
        if stat.S_ISLNK(info.st_mode):
            return
        if info.st_nlink > 1 and not stat.S_ISDIR(info.st_mode):
            key = (info.st_dev, info.st_ino)
            if key in self._seen:
                return
            self._seen.add(key)
        self.disk_bytes += info.st_blocks * BLOCK_BYTES

    def _visit(self, *, name: str, prefix: str, fd: int) -> TreeEntry | None:
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            self._account(info)
            return _entry_for(name=name, relative=f"{prefix}{name}", info=info, fd=fd)
        except (OSError, ValueError) as error:
            # ValueError: an entry TreeEntry refuses (a link with a blank target) is skipped.
            LOGGER.info("Skipping %s%s in cache tree: %s", prefix, name, error)
            self.skipped += 1
            return None

    def _read(self, *, fd: int, prefix: str) -> list[str]:
        """Record the children of an open directory; return the names of its subdirectories."""
        try:
            with os.scandir(fd) as scanner:
                names = sorted(child.name for child in scanner)
        except OSError as error:
            LOGGER.info("Cannot list %s in cache tree: %s", prefix or "root", error)
            self.skipped += 1
            return []
        subdirs: list[str] = []
        for name in names:
            self._count += 1
            pace(count=self._count, sleep=self._sleep)
            node = self._visit(name=name, prefix=prefix, fd=fd)
            if node is None:
                continue
            self.entries.append(node)
            if node.type is EntryType.DIR:
                subdirs.append(name)
        return subdirs

    def _descend(self, *, name: str, parent: int, prefix: str) -> Frame | None:
        try:
            fd = os.open(name, DIR_FLAGS, dir_fd=parent)
        except OSError as error:
            # Out of descriptors hides a whole subtree: say so louder than a routine change.
            level = logging.WARNING if error.errno in OUT_OF_DESCRIPTORS else logging.INFO
            LOGGER.log(level, "Skipping %s%s in cache tree: %s", prefix, name, error)
            self.skipped += 1
            return None
        child_prefix = f"{prefix}{name}/"
        try:
            return fd, child_prefix, self._read(fd=fd, prefix=child_prefix)
        except BaseException:
            os.close(fd)
            raise

    def run(self, *, root: Path) -> None:
        try:
            root_fd = os.open(root, DIR_FLAGS)
        except OSError as error:
            LOGGER.info("Cannot open %s as a cache tree: %s", root, error)
            self.skipped += 1
            return
        stack: list[Frame] = [(root_fd, "", [])]
        try:
            self._account(os.fstat(root_fd))
            stack[0] = (root_fd, "", self._read(fd=root_fd, prefix=""))
            while stack:
                fd, prefix, subdirs = stack[-1]
                if not subdirs:
                    os.close(fd)
                    stack.pop()
                    continue
                frame = self._descend(name=subdirs.pop(), parent=fd, prefix=prefix)
                if frame is not None:
                    stack.append(frame)
        except BaseException:
            for fd, _, _ in stack:
                os.close(fd)
            raise


def list_tree(*, root: Path, sleep: Callable[[float], None]) -> TreeListing:
    """Observe the tree under ``root`` without following links (S5).

    File sizes are disk space (``st_blocks * 512``), kept on every path: hard links are told
    apart by (st_dev, st_ino), which the core uses to count each file once. ``disk_bytes`` is
    the whole tree measured as ``measure_dir_size`` does. Symlinks keep their raw ``readlink``
    text and are never resolved. Unreadable or vanished entries are skipped and counted in
    ``skipped``; nothing is raised for them. ``sleep`` is called at the cadence of
    ``measure_dir_size`` and whatever it raises (a cancelled scan) propagates.
    """
    walk = _Walk(sleep=sleep)
    walk.run(root=root)
    return TreeListing(
        root=str(root),
        entries=tuple(walk.entries),
        disk_bytes=walk.disk_bytes,
        skipped=walk.skipped,
    )
