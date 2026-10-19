"""Sub-rows of a cache with items: one per item, the shared and unattributed rest."""

import pytest

from tests.core.disk_helpers import MB
from wimm.core.constants import CACHE_ITEMS_CAP
from wimm.model.cache_items import CacheItem, CacheRest
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import CacheItemKind
from wimm.ui.disk_items import ItemRowsView, item_rows

SHARED_TITLE = "Condiviso fra più elementi"
UNATTRIBUTED_TITLE = "Non attribuito"


def _item(*, index: int, size: int) -> CacheItem:
    return CacheItem(
        id=f"models--org--m{index}",
        title=f"org/m{index}",
        path=f"/home/u/.cache/huggingface/hub/models--org--m{index}",
        size=size,
        st_ino=100 + index,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
    )


def _entry(*, count: int, shared: int = 0, unattributed: int = 0) -> CacheEntry:
    items = tuple(_item(index=i, size=(count - i) * MB) for i in range(count))
    return CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/home/u/.cache/huggingface/hub",
        size=sum(item.size for item in items) + shared + unattributed,
        st_ino=11,
        st_dev=2049,
        items=items,
        rest=CacheRest(shared=shared, unattributed=unattributed),
    )


def _titles(*, view: ItemRowsView) -> list[str]:
    return [row.title for row in view.rows]


def test_item_rows_five_models_and_unattributed() -> None:
    view = item_rows(entry=_entry(count=5, unattributed=3 * MB))

    assert _titles(view=view) == [f"org/m{i}" for i in range(5)] + [UNATTRIBUTED_TITLE]
    assert view.more_text is None
    first = view.rows[0]
    assert (first.subtitle, first.size_text) == (
        "/home/u/.cache/huggingface/hub/models--org--m0",
        "5 MB",
    )


def test_item_rows_have_no_action_and_no_badge() -> None:
    view = item_rows(entry=_entry(count=2, shared=MB, unattributed=MB))

    assert all(
        (row.action_kind, row.target_id, row.risk, row.risk_text, row.risk_style)
        == (None, None, None, None, None)
        for row in view.rows
    )


def test_item_rows_cap_hides_the_rest_behind_a_counter() -> None:
    view = item_rows(entry=_entry(count=CACHE_ITEMS_CAP + 10))

    assert len(view.rows) == CACHE_ITEMS_CAP
    assert view.more_text == "e altre 10"


def test_item_rows_at_the_cap_hide_nothing() -> None:
    view = item_rows(entry=_entry(count=CACHE_ITEMS_CAP))

    assert (len(view.rows), view.more_text) == (CACHE_ITEMS_CAP, None)


@pytest.mark.parametrize(("shared", "expected"), [(0, False), (2 * MB, True)])
def test_item_rows_shared_row_only_when_shared_bytes(*, shared: int, expected: bool) -> None:
    view = item_rows(entry=_entry(count=2, shared=shared))

    assert (SHARED_TITLE in _titles(view=view)) is expected
    if expected:
        row = view.rows[-1]
        assert (row.title, row.size_text) == (SHARED_TITLE, "2 MB")


@pytest.mark.parametrize(("unattributed", "expected"), [(0, False), (MB, True)])
def test_item_rows_unattributed_row_only_when_bytes(*, unattributed: int, expected: bool) -> None:
    view = item_rows(entry=_entry(count=2, unattributed=unattributed))

    assert (UNATTRIBUTED_TITLE in _titles(view=view)) is expected


def test_item_rows_unattributed_explains_it_goes_with_the_whole_cache() -> None:
    view = item_rows(entry=_entry(count=1, unattributed=MB))

    text = view.rows[-1].subtitle
    assert "nessun elemento" in text
    assert "tutta la cache" in text


def test_item_rows_shared_comes_before_unattributed() -> None:
    view = item_rows(entry=_entry(count=1, shared=MB, unattributed=MB))

    assert _titles(view=view)[-2:] == [SHARED_TITLE, UNATTRIBUTED_TITLE]


def test_item_rows_cache_without_items_has_no_rows() -> None:
    entry = CacheEntry(kind=CacheKind.UV, path="/home/u/.cache/uv", size=MB, st_ino=11, st_dev=2049)

    assert item_rows(entry=entry) == ItemRowsView()
