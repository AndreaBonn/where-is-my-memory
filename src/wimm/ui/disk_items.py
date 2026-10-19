"""The sub-rows of a cache with items: one per item, then what no single item owns."""

from dataclasses import dataclass

from wimm.core.constants import CACHE_ITEMS_CAP
from wimm.i18n import _
from wimm.model.disk import CacheEntry
from wimm.ui.disk_model import DiskRowView, make_row, more_text
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


def item_rows(*, entry: CacheEntry) -> ItemRowsView:
    """Sub-rows of `entry`, no action on any (L2); empty for a cache without items."""
    if not entry.items:
        return ItemRowsView()
    shown = entry.items[:CACHE_ITEMS_CAP]
    rows = [
        make_row(title=item.title, subtitle=item.path, size=item.size, action=None)
        for item in shown
    ]
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


def _rest_row(*, title: str, text: str, size: int) -> DiskRowView:
    return make_row(title=_(title), subtitle=_(text), size=size, action=None)
