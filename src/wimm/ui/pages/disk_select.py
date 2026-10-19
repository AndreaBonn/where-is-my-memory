"""The check boxes of the Disco selection mode (S16): they follow a pure `DiskSelection`."""

from collections.abc import Callable

from gi.repository import Gtk

from wimm.i18n import _
from wimm.model.actions import selected_entry_id
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_selection import DiskSelection, is_selectable

CheckFactory = Callable[[DiskRowView], Gtk.CheckButton | None]
Tick = tuple[str, Gtk.CheckButton, DiskRowView]


class SelectionChecks:
    """Owns the selection and every check box built for it, per section."""

    def __init__(self, *, on_change: Callable[[DiskSelection], None]) -> None:
        self.selection = DiskSelection()
        self._on_change = on_change
        self._active = False
        self._syncing = False
        self._checks: list[Tick] = []

    @property
    def active(self) -> bool:
        """True while the Seleziona mode is on."""
        return self._active

    def owned(self, *, owner: str) -> "OwnerChecks":
        """The checks of one section, which it drops when it rebuilds its rows."""
        return OwnerChecks(selection=self, owner=owner)

    def drop(self, *, owner: str) -> None:
        """Forget the checks of rows that are being rebuilt."""
        self._checks = [tick for tick in self._checks if tick[0] != owner]

    def set_active(self, *, active: bool) -> None:
        """Enter or leave the mode; leaving clears what was ticked."""
        self._active = active
        if not active:
            self.selection = self.selection.after_new_report()
        self.refresh()

    def new_report(self) -> None:
        """S17: a new disk report clears the selection."""
        self.selection = self.selection.after_new_report()
        self.refresh()

    def refresh(self) -> None:
        """Show the checks in the mode, tick the selected ones and tell the owner."""
        self._syncing = True
        for _owner, check, row in self._checks:
            check.set_visible(self._active)
            check.set_active(self.selection.is_selected(row=row))
        self._syncing = False
        self._on_change(self.selection)

    def make(
        self, *, owner: str, row: DiskRowView, parent: DiskRowView | None
    ) -> Gtk.CheckButton | None:
        if not is_selectable(row=row) or row.action_kind is None:
            return None
        entry = selected_entry_id(kind=row.action_kind, target_id=row.target_id)
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, visible=self._active)
        check.set_name(entry)
        check.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Seleziona {name}").format(name=row.title)]
        )
        check.set_active(self.selection.is_selected(row=row))
        check.connect("toggled", lambda *_a: self._toggled(row=row, parent=parent))
        self._checks.append((owner, check, row))
        return check

    def _toggled(self, *, row: DiskRowView, parent: DiskRowView | None) -> None:
        if self._syncing:
            return
        self.selection = self.selection.toggle(row=row, parent=parent)
        self.refresh()


class OwnerChecks:
    """The check makers of one section: for its rows, and for the sub-rows of a cache row."""

    def __init__(self, *, selection: SelectionChecks, owner: str) -> None:
        self._selection, self._owner = selection, owner

    def make(self, row: DiskRowView) -> Gtk.CheckButton | None:
        """The check of a section row, None when the row cannot be selected."""
        return self._selection.make(owner=self._owner, row=row, parent=None)

    def children_of(self, parent: DiskRowView | None) -> CheckFactory:
        """The maker for the sub-rows of ``parent``, which a whole-cache tick replaces."""

        def make(row: DiskRowView) -> Gtk.CheckButton | None:
            return self._selection.make(owner=self._owner, row=row, parent=parent)

        return make

    def drop(self) -> None:
        """Forget this section's checks before its rows are rebuilt."""
        self._selection.drop(owner=self._owner)
