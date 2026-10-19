import logging
import os
import stat
from pathlib import Path

from wimm.core.cache_items import EntryType, TreeEntry, TreeListing
from wimm.model.disk import CacheKind

LOGGER = logging.getLogger(__name__)

# Kinds whose tree is read a second time to split them into items; must match `items_for`.
ITEM_KINDS = frozenset({CacheKind.HUGGINGFACE})
BLOCK_BYTES = 512


def _entry_for(
    *, relative: str, info: os.stat_result, path: str, seen: set[tuple[int, int]]
) -> TreeEntry | None:
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        return TreeEntry(path=relative, type=EntryType.SYMLINK, target=os.readlink(path))
    if stat.S_ISDIR(mode):
        return TreeEntry(path=relative, type=EntryType.DIR, st_ino=info.st_ino, st_dev=info.st_dev)
    if not stat.S_ISREG(mode):
        return None
    identity = (info.st_dev, info.st_ino)
    size = info.st_blocks * BLOCK_BYTES
    if info.st_nlink > 1:
        size = 0 if identity in seen else size
        seen.add(identity)
    return TreeEntry(path=relative, type=EntryType.FILE, size=size)


def _visit(*, entry: os.DirEntry[str], prefix: str, seen: set[tuple[int, int]]) -> TreeEntry | None:
    try:
        info = entry.stat(follow_symlinks=False)
        return _entry_for(relative=f"{prefix}{entry.name}", info=info, path=entry.path, seen=seen)
    except OSError as error:
        LOGGER.info("Skipping %s in cache tree: %s", entry.path, error)
        return None


def list_tree(*, root: Path) -> TreeListing:
    """Observe the tree under ``root`` without following links (S5).

    File sizes are disk space (``st_blocks * 512``) and a hard link seen again counts 0, as
    in ``measure_dir_size``. Symlinks keep their raw ``readlink`` text and are never resolved.
    Unreadable or vanished entries are skipped; nothing is raised for them.
    """
    found: list[TreeEntry] = []
    seen: set[tuple[int, int]] = set()
    pending = [""]
    while pending:
        parent = pending.pop()
        folder = os.path.join(root, parent) if parent else str(root)
        try:
            with os.scandir(folder) as scanner:
                children = sorted(scanner, key=lambda child: child.name)
        except OSError as error:
            LOGGER.info("Cannot list %s in cache tree: %s", folder, error)
            continue
        for child in children:
            node = _visit(entry=child, prefix=f"{parent}/" if parent else "", seen=seen)
            if node is None:
                continue
            found.append(node)
            if node.type is EntryType.DIR:
                pending.append(node.path)
    return TreeListing(root=str(root), entries=tuple(found))
