"""What the user ticked on the Disco page (S16, S17): a pure value, rebuilt on every change.

A whole cache and its items are never ticked together: ticking one drops the other. A new
disk report clears everything, so nothing ticked against an old report is ever confirmed.
"""

from dataclasses import dataclass

from wimm.model.actions import SELECTABLE_KINDS, selected_entry_id
from wimm.model.enums import Risk
from wimm.ui.disk_model import DiskRowView

__all__ = ["DiskSelection", "is_selectable"]


def is_selectable(*, row: DiskRowView) -> bool:
    """A row with a selectable action that is not a danger one (Q3=A: those go alone)."""
    return row.action_kind in SELECTABLE_KINDS and row.risk is not Risk.DANGER


def _entry_of(*, row: DiskRowView) -> str:
    if row.action_kind is None:  # callers check is_selectable first
        raise ValueError("a row without an action cannot be selected")
    return selected_entry_id(kind=row.action_kind, target_id=row.target_id)


@dataclass(frozen=True, slots=True)
class DiskSelection:
    """Ticked rows as (entry id, bytes) pairs; the ids are what DISK_FREE_SELECTED takes."""

    sizes: frozenset[tuple[str, int]] = frozenset()

    @property
    def entries(self) -> frozenset[str]:
        return frozenset(entry for entry, _ in self.sizes)

    @property
    def count(self) -> int:
        return len(self.sizes)

    @property
    def total_bytes(self) -> int:
        return sum(size for _, size in self.sizes)

    def is_selected(self, *, row: DiskRowView) -> bool:
        return is_selectable(row=row) and _entry_of(row=row) in self.entries

    def toggle(self, *, row: DiskRowView, parent: DiskRowView | None) -> "DiskSelection":
        """Tick or untick `row`; `parent` is the cache row of an item sub-row, else None."""
        if not is_selectable(row=row):
            return self
        entry = _entry_of(row=row)
        if entry in self.entries:
            return DiskSelection(sizes=frozenset(p for p in self.sizes if p[0] != entry))
        others = _related(row=row, parent=parent)
        kept = frozenset(p for p in self.sizes if p[0] not in others)
        return DiskSelection(sizes=kept | {(entry, row.size_bytes)})

    def after_new_report(self) -> "DiskSelection":
        """A new report clears the selection (S17)."""
        return DiskSelection()


def _related(*, row: DiskRowView, parent: DiskRowView | None) -> frozenset[str]:
    """Entries that cannot stay ticked with `row`: its items, or the cache it belongs to."""
    if parent is not None and is_selectable(row=parent):
        return frozenset({_entry_of(row=parent)})
    return frozenset(_entry_of(row=item) for item in row.items if is_selectable(row=item))
