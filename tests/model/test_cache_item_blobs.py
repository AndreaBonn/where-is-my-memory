import pytest

from wimm.model import CacheItem, CacheItemKind, ItemBlob


def _item(*, blobs: tuple[ItemBlob, ...] = ()) -> CacheItem:
    return CacheItem(
        id="models--org--a",
        title="org/a",
        path="/home/u/.cache/huggingface/hub/models--org--a",
        size=10,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
        blobs=blobs,
    )


def test_an_item_has_no_blobs_by_default() -> None:
    item = CacheItem(
        id="models--org--a",
        title="org/a",
        path="/p",
        size=1,
        st_ino=1,
        st_dev=1,
        kind=CacheItemKind.HF_MODEL,
    )
    assert item.blobs == ()


def test_an_item_carries_its_store_blobs() -> None:
    blob = ItemBlob(path="hub/blobs/3b/excl", size=2000, st_ino=7, st_dev=2049)
    assert _item(blobs=(blob,)).blobs == (blob,)


def test_item_refuses_duplicate_blob_paths() -> None:
    blob = ItemBlob(path="hub/blobs/3b/excl", size=2000, st_ino=7, st_dev=2049)
    with pytest.raises(ValueError, match="unique"):
        _item(blobs=(blob, blob))


def test_item_refuses_a_list_of_blobs() -> None:
    with pytest.raises(ValueError, match="blobs"):
        _item(blobs=[])  # type: ignore[arg-type]
