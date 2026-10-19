from dataclasses import dataclass

from .enums import CacheItemKind
from .validation import ImmutableModel, require_bytes, require_nonnegative, require_text


@dataclass(frozen=True, slots=True)
class CacheItem(ImmutableModel):
    """One removable part of a cache, e.g. a HuggingFace model.

    `id` is stable within the cache (the folder name, `models--org--name`); `size` is
    what the item alone holds.
    """

    id: str
    title: str
    path: str
    size: int
    st_ino: int
    st_dev: int
    kind: CacheItemKind

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_text(value=self.id, field="id")
        require_text(value=self.title, field="title")
        require_text(value=self.path, field="path")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")


@dataclass(frozen=True, slots=True)
class CacheRest(ImmutableModel):
    """Bytes of a cache that no single item owns.

    `shared` is reachable from links of two or more items; `unattributed` lies in the
    cache outside every item.
    """

    shared: int = 0
    unattributed: int = 0

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_bytes(value=self.shared, field="shared")
        require_bytes(value=self.unattributed, field="unattributed")
