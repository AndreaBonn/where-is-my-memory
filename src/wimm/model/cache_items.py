import re
from dataclasses import dataclass

from .enums import CacheItemKind
from .validation import ImmutableModel, require_bytes, require_nonnegative, require_text

MODEL_ID_PATTERN = re.compile(r"[0-9a-f]{12}")


@dataclass(frozen=True, slots=True)
class ItemBlob(ImmutableModel):
    """A hub-store file that only one item reaches, so it goes with the item.

    `path` is relative to the cache root, POSIX style, and never leaves it.
    """

    path: str
    size: int
    st_ino: int
    st_dev: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_text(value=self.path, field="path")
        if self.path.startswith("/") or any(p in ("", "..") for p in self.path.split("/")):
            raise ValueError("path must be relative, without empty or '..' components")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")


def require_unique_blob_paths(*, blobs: tuple[ItemBlob, ...]) -> None:
    paths = [blob.path for blob in blobs]
    if len(set(paths)) != len(paths):
        raise ValueError("blob paths must be unique")


@dataclass(frozen=True, slots=True)
class CacheItem(ImmutableModel):
    """One removable part of a cache, e.g. a HuggingFace model.

    `id` is stable within the cache (the folder name, `models--org--name`); `size` is
    what the item alone holds. `blobs` are the store files outside the folder that only
    this item reaches (removed with it); files inside the folder are not listed.
    `model_id` is the 12-hex id `ollama list` prints; empty for every other item.
    """

    id: str
    title: str
    path: str
    size: int
    st_ino: int
    st_dev: int
    kind: CacheItemKind
    blobs: tuple[ItemBlob, ...] = ()
    model_id: str = ""

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_unique_blob_paths(blobs=self.blobs)
        require_text(value=self.id, field="id")
        require_text(value=self.title, field="title")
        require_text(value=self.path, field="path")
        require_bytes(value=self.size, field="size")
        require_nonnegative(value=self.st_ino, field="st_ino")
        require_nonnegative(value=self.st_dev, field="st_dev")
        if type(self.model_id) is not str or (
            self.model_id and not MODEL_ID_PATTERN.fullmatch(self.model_id)
        ):
            raise ValueError("model_id must be empty or 12 lowercase hex digits")


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
