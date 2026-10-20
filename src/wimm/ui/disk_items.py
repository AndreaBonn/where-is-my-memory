"""The sub-rows of a cache with items: one per item, then what no single item owns."""

from dataclasses import dataclass, replace

from wimm.core.constants import CACHE_ITEMS_CAP
from wimm.core.ollama_served import ServedStore
from wimm.core.planning_cache_item import ITEM_TARGET_SEPARATOR
from wimm.core.risk import RiskTarget
from wimm.core.row_consequence import row_consequence
from wimm.i18n import _
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import ActionSpec, DiskRowView, make_row, more_text
from wimm.ui.disk_ollama import ollama_offer
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


def item_rows(
    *, entry: CacheEntry, removable: bool = True, served: ServedStore | None = None
) -> ItemRowsView:
    """Sub-rows of `entry`: an item can be removed, the rest rows cannot; empty without items.

    `removable` is False when the tool that removes this cache's items is missing; `served`
    is the ollama server situation of the report (None: not known), which decides the
    ollama models.
    """
    if not entry.items:
        return ItemRowsView()
    shown = entry.items[:CACHE_ITEMS_CAP]
    rows = [_item_row(entry=entry, item=item, removable=removable, served=served) for item in shown]
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


def _item_row(
    *, entry: CacheEntry, item: CacheItem, removable: bool, served: ServedStore | None
) -> DiskRowView:
    offered, reason = ollama_offer(kind=entry.kind, item=item, served=served)
    action = _item_action(entry=entry, item=item) if removable and offered else None
    subtitle = f"ID {item.model_id}" if entry.kind is CacheKind.OLLAMA_SYSTEM else item.path
    row = make_row(title=item.title, subtitle=subtitle, size=item.size, action=action)
    return row if action else replace(row, note=reason)


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
