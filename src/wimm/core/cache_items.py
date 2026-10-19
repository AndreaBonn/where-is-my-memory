"""The parts of one cache the user can remove on their own, and what is left over (S5-S8)."""

from dataclasses import dataclass
from enum import Enum

from wimm.model.cache_items import CacheItem, CacheRest
from wimm.model.disk import CacheKind
from wimm.model.validation import require_bytes, require_nonnegative


class EntryType(Enum):
    FILE = "file"
    DIR = "dir"
    SYMLINK = "symlink"


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One node of a cache tree, as observed without following links.

    `path` is relative to the listing root, POSIX style. `size` is set for regular files,
    `target` is the raw `readlink` text of a symlink, `st_ino`/`st_dev` identify a folder.
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


@dataclass(frozen=True, slots=True)
class TreeListing:
    """The observed tree of one cache: its absolute root and every entry below it."""

    root: str
    entries: tuple[TreeEntry, ...]


def _rest_for(*, items: tuple[CacheItem, ...], shared: int, size: int) -> CacheRest:
    unattributed = max(size - sum(item.size for item in items) - shared, 0)
    return CacheRest(shared=shared, unattributed=unattributed)


def items_for(
    kind: CacheKind, listing: TreeListing, size: int
) -> tuple[tuple[CacheItem, ...], CacheRest]:
    """Split a cache into items sorted by size descending (ties by id) and the rest.

    Kinds with no item rule give no items and an all-zero rest. Items are never truncated:
    the cap on what is shown belongs to the UI (`CACHE_ITEMS_CAP`).
    """
    if kind is not CacheKind.HUGGINGFACE:
        return (), CacheRest()
    # Imported here because the HuggingFace rule builds on the tree types defined above.
    from .cache_items_hf import hf_items

    found, shared = hf_items(listing=listing)
    items = tuple(sorted(found, key=lambda item: (-item.size, item.id)))
    return items, _rest_for(items=items, shared=shared, size=size)
