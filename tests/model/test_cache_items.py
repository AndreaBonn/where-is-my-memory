import dataclasses
from collections.abc import Callable

import pytest

from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, CacheRest

MB = 1_000_000


def item(*, id: str = "models--org--a", size: int = MB) -> CacheItem:
    return CacheItem(
        id=id,
        title="org/a",
        path=f"/home/u/.cache/huggingface/hub/{id}",
        size=size,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
    )


def entry(
    *, size: int, items: tuple[CacheItem, ...] = (), rest: CacheRest | None = None
) -> CacheEntry:
    return CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/home/u/.cache/huggingface",
        size=size,
        st_ino=11,
        st_dev=2049,
        items=items,
        rest=rest or CacheRest(),
    )


def test_cache_without_items_has_empty_items_and_zero_rest() -> None:
    built = entry(size=MB)

    assert built.items == ()
    assert built.rest == CacheRest(shared=0, unattributed=0)


def test_item_kinds_cover_every_cache_with_an_item_rule() -> None:
    assert {kind.value for kind in CacheItemKind} == {
        "hf_model",
        "hf_dataset",
        "hf_space",
        "android_package",
        "android_avd",
        "playwright_browser",
        "jetbrains_product",
        "ollama_model",
    }


def test_duplicate_item_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        entry(size=10 * MB, items=(item(), item()))


def test_items_plus_rest_equal_to_size_are_accepted() -> None:
    built = entry(
        size=10 * MB,
        items=(item(id="a", size=4 * MB), item(id="b", size=3 * MB)),
        rest=CacheRest(shared=2 * MB, unattributed=MB),
    )

    assert built.items[1].size == 3 * MB


def test_items_plus_rest_larger_than_size_are_rejected() -> None:
    with pytest.raises(ValueError, match="exceed"):
        entry(
            size=10 * MB - 1,
            items=(item(id="a", size=4 * MB), item(id="b", size=3 * MB)),
            rest=CacheRest(shared=2 * MB, unattributed=MB),
        )


@pytest.mark.parametrize(
    "field,build",
    [
        ("size", lambda: dataclasses.replace(item(), size=-1)),
        ("st_ino", lambda: dataclasses.replace(item(), st_ino=-1)),
        ("st_dev", lambda: dataclasses.replace(item(), st_dev=-1)),
        ("id", lambda: dataclasses.replace(item(), id=" ")),
        ("title", lambda: dataclasses.replace(item(), title=" ")),
        ("path", lambda: dataclasses.replace(item(), path=" ")),
        ("shared", lambda: CacheRest(shared=-1)),
        ("unattributed", lambda: CacheRest(unattributed=-1)),
    ],
)
def test_invalid_item_or_rest_field_is_rejected(field: str, build: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match=field):
        build()
