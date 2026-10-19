"""The sub-rows of a cache with items: one per item, then what no single item owns."""

from dataclasses import dataclass

from wimm.core.constants import CACHE_ITEMS_CAP
from wimm.core.item_tools import is_item_removable
from wimm.core.planning_cache_item import ITEM_TARGET_SEPARATOR
from wimm.core.risk import RiskTarget
from wimm.core.row_consequence import row_consequence
from wimm.i18n import _
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheEntry
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import ActionSpec, DiskRowView, make_row, more_text
from wimm.ui.disk_texts import (
    SHARED_ROW_TEXT,
    SHARED_ROW_TITLE,
    UNATTRIBUTED_ROW_TEXT,
    UNATTRIBUTED_ROW_TITLE,
)


@dataclass(frozen=True, slots=True)
class ItemRowsView:
    """Sub-rows of one cache, and the "e altre N" counter when the cap hid items."""

    rows: tuple[DiskRowView, ...] = ()
    more_text: str | None = None


def item_rows(*, entry: CacheEntry, removable: bool = True) -> ItemRowsView:
    """Sub-rows of `entry`: an item can be removed, the rest rows cannot; empty without items.

    `removable` is False when the tool that removes this cache's items is missing.
    """
    if not entry.items:
        return ItemRowsView()
    shown = entry.items[:CACHE_ITEMS_CAP]
    rows = [_item_row(entry=entry, item=item, removable=removable) for item in shown]
    if entry.rest.shared > 0:
        rows.append(_rest_row(title=SHARED_ROW_TITLE, text=SHARED_ROW_TEXT, size=entry.rest.shared))
    if entry.rest.unattributed > 0:
        rows.append(
            _rest_row(
                title=UNATTRIBUTED_ROW_TITLE,
                text=UNATTRIBUTED_ROW_TEXT,
                size=entry.rest.unattributed,
            )
        )
    hidden = len(entry.items) - len(shown)
    return ItemRowsView(rows=tuple(rows), more_text=more_text(count=hidden))


def _item_row(*, entry: CacheEntry, item: CacheItem, removable: bool) -> DiskRowView:
    offered = removable and is_item_removable(item=item)
    action = _item_action(entry=entry, item=item) if offered else None
    return make_row(title=item.title, subtitle=item.path, size=item.size, action=action)


def _rest_row(*, title: str, text: str, size: int) -> DiskRowView:
    return make_row(title=_(title), subtitle=_(text), size=size, action=None)


def _item_action(*, entry: CacheEntry, item: CacheItem) -> ActionSpec:
    """Same target and consequence text as the plan, so the row and the dialog agree."""
    kind = ActionKind.CACHE_ITEM_REMOVE
    target = RiskTarget(kind="cache_item", item_kind=item.kind)
    return ActionSpec(
        kind=kind,
        target=target,
        target_id=f"{entry.kind.value}{ITEM_TARGET_SEPARATOR}{item.id}",
        consequence=row_consequence(action=kind, target=target),
    )
