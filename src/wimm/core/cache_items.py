"""The parts of one cache the user can remove on their own, and what is left over (S5-S8)."""

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
    """The observed tree of one cache: its absolute root and every entry below it."""

    root: str
    entries: tuple[TreeEntry, ...]

    def __post_init__(self) -> None:
        require_text(value=self.root, field="root")
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
