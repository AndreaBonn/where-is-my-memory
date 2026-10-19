"""S16-S17: what the user ticked on the Disco page, as a pure value."""

from wimm.model.actions import selected_entry_id
from wimm.model.enums import ActionKind, Risk
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_selection import DiskSelection, is_selectable

MB = 1_000_000


def row(
    *, kind: ActionKind | None, target: str | None, size: int = MB, risk: Risk = Risk.SAFE
) -> DiskRowView:
    return DiskRowView(
        title=target or "row",
        subtitle="",
        size_text="",
        risk=risk if kind is not None else None,
        action_kind=kind,
        target_id=target,
        size_bytes=size,
    )


MODEL = row(kind=ActionKind.CACHE_ITEM_REMOVE, target="huggingface:models--a--b", risk=Risk.CAUTION)
OTHER_MODEL = row(kind=ActionKind.CACHE_ITEM_REMOVE, target="huggingface:models--c--d", size=3 * MB)
HUB = row(kind=ActionKind.CACHE_CLEAN, target="huggingface", size=9 * MB, risk=Risk.CAUTION)
HUB_WITH_ITEMS = DiskRowView(
    title=HUB.title,
    subtitle="",
    size_text="",
    risk=HUB.risk,
    action_kind=HUB.action_kind,
    target_id=HUB.target_id,
    size_bytes=HUB.size_bytes,
    items=(MODEL, OTHER_MODEL),
)
BUILD_CACHE = row(kind=ActionKind.BUILDER_PRUNE, target=None, size=2 * MB)


def test_a_row_with_a_selectable_action_and_no_danger_is_selectable() -> None:
    assert is_selectable(row=MODEL)
    assert is_selectable(row=BUILD_CACHE)


def test_danger_rows_and_rows_without_action_are_not_selectable() -> None:
    danger = row(kind=ActionKind.VOLUME_REMOVE, target="data", risk=Risk.DANGER)
    plain = row(kind=None, target=None)
    assert not is_selectable(row=danger)
    assert not is_selectable(row=plain)


def test_toggling_adds_then_removes_a_row() -> None:
    once = DiskSelection().toggle(row=MODEL, parent=HUB_WITH_ITEMS)
    expected = selected_entry_id(kind=ActionKind.CACHE_ITEM_REMOVE, target_id=MODEL.target_id)
    assert once.entries == frozenset({expected})
    assert once.toggle(row=MODEL, parent=HUB_WITH_ITEMS).entries == frozenset()


def test_an_unselectable_row_is_ignored() -> None:
    danger = row(kind=ActionKind.VOLUME_REMOVE, target="data", risk=Risk.DANGER)
    assert DiskSelection().toggle(row=danger, parent=None).entries == frozenset()


def test_count_and_bytes_add_up_the_ticked_rows() -> None:
    selection = (
        DiskSelection()
        .toggle(row=MODEL, parent=HUB_WITH_ITEMS)
        .toggle(row=BUILD_CACHE, parent=None)
    )
    assert selection.count == 2
    assert selection.total_bytes == MB + 2 * MB


def test_ticking_the_whole_cache_drops_its_items() -> None:
    items = (
        DiskSelection()
        .toggle(row=MODEL, parent=HUB_WITH_ITEMS)
        .toggle(row=OTHER_MODEL, parent=HUB_WITH_ITEMS)
    )
    whole = items.toggle(row=HUB_WITH_ITEMS, parent=None)
    assert whole.count == 1
    assert whole.total_bytes == HUB.size_bytes
    assert whole.is_selected(row=HUB_WITH_ITEMS)
    assert not whole.is_selected(row=MODEL)


def test_ticking_an_item_drops_its_whole_cache() -> None:
    whole = DiskSelection().toggle(row=HUB_WITH_ITEMS, parent=None)
    item = whole.toggle(row=MODEL, parent=HUB_WITH_ITEMS)
    assert item.is_selected(row=MODEL)
    assert not item.is_selected(row=HUB_WITH_ITEMS)
    assert item.total_bytes == MODEL.size_bytes


def test_items_of_another_cache_stay_when_a_cache_is_ticked() -> None:
    other_cache = row(kind=ActionKind.CACHE_CLEAN, target="npm", size=4 * MB)
    selection = (
        DiskSelection()
        .toggle(row=MODEL, parent=HUB_WITH_ITEMS)
        .toggle(row=other_cache, parent=None)
    )
    assert selection.count == 2


def test_a_new_report_clears_the_selection() -> None:
    selection = DiskSelection().toggle(row=MODEL, parent=HUB_WITH_ITEMS)
    assert selection.after_new_report() == DiskSelection()
    assert selection.count == 1
