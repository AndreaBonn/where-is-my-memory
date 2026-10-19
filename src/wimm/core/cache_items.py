"""The parts of one cache the user can remove on their own, and what is left over (S5-S8)."""

from collections import defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass
from enum import Enum

from wimm.model.cache_items import CacheItem, CacheRest
from wimm.model.disk import CacheKind
from wimm.model.validation import require_bytes, require_nonnegative, require_text

PARENT = ".."


class EntryType(Enum):
    FILE = "file"
    DIR = "dir"
    SYMLINK = "symlink"


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One node of a cache tree, as observed without following links.

    `path` is relative to the listing root, POSIX style. `size` is set for regular files,
    `target` is the raw `readlink` text of a symlink, `st_ino`/`st_dev` identify the node
    (a folder, or the file itself so that hard links can be told apart).
    """

    path: str
    type: EntryType
    size: int = 0
    target: str | None = None
    st_ino: int = 0
    st_dev: int = 0

    def __post_init__(self) -> None:
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")
        if not self.path:
            raise ValueError("path must not be empty")
        if self.type is EntryType.SYMLINK:
            require_text(value=self.target, field="target")  # type: ignore[arg-type]
            if self.size:
                raise ValueError("a symlink has no size of its own")
        elif self.target is not None:
            raise ValueError("only a symlink has a target")
        if self.type is EntryType.DIR and self.size:
            raise ValueError("a directory has no size of its own")


def _require_relative(path: str) -> None:
    if path.startswith("/") or PARENT in path.split("/"):
        raise ValueError(f"path must be relative without '..': {path!r}")


@dataclass(frozen=True, slots=True)
class TreeListing:
    """The observed tree of one cache: its absolute root and every entry below it.

    `disk_bytes` is the disk space of the whole tree as one walk measured it, directories and
    the root included (a directory carries no size in `entries`), so a cache is sized by the
    same observation its items come from. `skipped` counts the entries or directories the walk
    could not read or open: when it is not zero the listing may be missing nodes, so nothing
    destructive may be decided from the absence of a link.
    """

    root: str
    entries: tuple[TreeEntry, ...]
    disk_bytes: int = 0
    skipped: int = 0

    def __post_init__(self) -> None:
        require_text(value=self.root, field="root")
        require_bytes(value=self.disk_bytes, field="disk_bytes")
        require_nonnegative(value=self.skipped, field="skipped")
        if not self.root.startswith("/"):
            raise ValueError("root must be absolute")
        if type(self.entries) is not tuple:
            raise ValueError("entries must be a tuple")
        paths = [entry.path for entry in self.entries]
        for path in paths:
            _require_relative(path)
        if len(set(paths)) != len(paths):
            raise ValueError("entry paths must be unique")


def _rest_for(*, items: tuple[CacheItem, ...], shared: int, size: int) -> CacheRest:
    unattributed = max(size - sum(item.size for item in items) - shared, 0)
    return CacheRest(shared=shared, unattributed=unattributed)


def folder_sizes(*, listing: TreeListing, folders: Collection[str]) -> tuple[dict[str, int], int]:
    """Disk bytes each folder holds alone, and the bytes held by two or more of them.

    A regular file counts for every folder that contains it; files are told apart by identity
    (device, inode), so a hard link counts once, and one reached from several folders is
    shared and belongs to none. Folders are paths relative to the listing root.
    """
    wanted = set(folders)
    claims: dict[tuple[int, int], set[str]] = defaultdict(set)
    sizes: dict[tuple[int, int], int] = {}
    for entry in listing.entries:
        if entry.type is not EntryType.FILE:
            continue
        parts = entry.path.split("/")[:-1]
        owners = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)} & wanted
        if owners:
            identity = (entry.st_dev, entry.st_ino)
            claims[identity] |= owners
            sizes[identity] = entry.size
    per_folder = dict.fromkeys(wanted, 0)
    shared = 0
    for identity, owners in claims.items():
        if len(owners) > 1:
            shared += sizes[identity]
        else:
            per_folder[next(iter(owners))] += sizes[identity]
    return per_folder, shared


ItemRule = Callable[..., tuple[tuple[CacheItem, ...], int]]


def _rule_for(kind: CacheKind) -> ItemRule | None:
    # Imported here because the rules build on the tree types defined above.
    if kind is CacheKind.HUGGINGFACE:
        from .cache_items_hf import hf_items

        return hf_items
    if kind is CacheKind.ANDROID_SDK:
        from .cache_items_android import sdk_items

        return sdk_items
    if kind is CacheKind.ANDROID_AVD:
        from .cache_items_android import avd_items

        return avd_items
    if kind is CacheKind.PLAYWRIGHT:
        from .cache_items_misc import playwright_items

        return playwright_items
    if kind is CacheKind.JETBRAINS:
        from .cache_items_misc import jetbrains_items

        return jetbrains_items
    return None


def items_for(
    kind: CacheKind, listing: TreeListing, size: int
) -> tuple[tuple[CacheItem, ...], CacheRest]:
    """Split a cache into items sorted by size descending (ties by id) and the rest.

    Kinds with no item rule give no items and an all-zero rest. Items are never truncated:
    the cap on what is shown belongs to the UI (`CACHE_ITEMS_CAP`).
    """
    rule = _rule_for(kind)
    if rule is None:
        return (), CacheRest()
    found, shared = rule(listing=listing)
    items = tuple(sorted(found, key=lambda item: (-item.size, item.id)))
    return items, _rest_for(items=items, shared=shared, size=size)
