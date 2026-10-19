"""Builders for the system ollama store entry (T-6.37a)."""

from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, CacheRest

MB = 1_000_000
MODEL_ID = "a2af6cc3eb7f"
SYSTEM_PATH = "ollama list"


def model(*, name: str = "gemma3:4b", model_id: str = MODEL_ID, size: int = MB) -> CacheItem:
    return CacheItem(
        id=name,
        title=name,
        path=f"ollama:{name}",
        size=size,
        st_ino=0,
        st_dev=0,
        kind=CacheItemKind.OLLAMA_MODEL,
        model_id=model_id,
    )


def system_entry(
    *,
    items: tuple[CacheItem, ...] | None = None,
    st_ino: int = 0,
    st_dev: int = 0,
    rest: CacheRest | None = None,
    size: int = 3 * MB,
) -> CacheEntry:
    return CacheEntry(
        kind=CacheKind.OLLAMA_SYSTEM,
        path=SYSTEM_PATH,
        size=size,
        st_ino=st_ino,
        st_dev=st_dev,
        items=(model(size=size),) if items is None else items,
        rest=rest or CacheRest(),
    )
