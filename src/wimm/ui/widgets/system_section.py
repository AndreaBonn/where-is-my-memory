"""Y1: the protected programs, closed at the bottom of the Panoramica instead of a tab."""

from gi.repository import Adw, Gtk

from wimm.i18n import N_, _
from wimm.model.snapshot import Snapshot
from wimm.ui.format import format_size
from wimm.ui.viewmodel import build_system_rows
from wimm.ui.views import SystemRow

TITLE = N_("Parti del sistema")
INTRO_TEXT = N_(
    "Questi programmi fanno funzionare il computer. "
    "Da qui non si possono chiudere, quindi non puoi rompere niente."
)
LOCK_ICON = "changes-prevent-symbolic"


def _lock() -> Gtk.Image:
    return Gtk.Image(icon_name=LOCK_ICON, accessible_role=Gtk.AccessibleRole.PRESENTATION)


def _row_widget(*, row: SystemRow) -> Adw.ActionRow:
    widget = Adw.ActionRow(title=row.label, subtitle=row.reason, use_markup=False)
    widget.add_prefix(_lock())
    memory = Gtk.Label(label=row.memory, valign=Gtk.Align.CENTER)
    memory.add_css_class("wimm-reclaim")
    widget.add_suffix(memory)
    return widget


class SystemSection(Gtk.ListBox):
    """Read-only list of the protected groups with the reason (RF-07), in one expander."""

    def __init__(self) -> None:
        super().__init__(selection_mode=Gtk.SelectionMode.NONE, visible=False)
        self.add_css_class("boxed-list")
        self.expander = Adw.ExpanderRow(subtitle=_(INTRO_TEXT), use_markup=False, subtitle_lines=0)
        self.expander.add_prefix(_lock())
        self.append(self.expander)
        self._rows: list[Adw.ActionRow] = []
        self._last: tuple[SystemRow, ...] | None = None

    @property
    def row_count(self) -> int:
        """Number of protected groups listed."""
        return len(self._last or ())

    def show_waiting(self) -> None:
        """Hide the section until the first snapshot arrives."""
        self.set_visible(False)

    def show_snapshot(self, *, snapshot: Snapshot) -> None:
        """List the protected groups, largest first, with their total in the title."""
        rows = build_system_rows(snapshot=snapshot)
        total = sum(item.memory for item in snapshot.protected_summary)
        self.expander.set_title(f"{_(TITLE)} · {format_size(size=total)}")
        if rows != self._last:
            self._last = rows
            for widget in self._rows:
                self.expander.remove(widget)
            self._rows = [_row_widget(row=row) for row in rows]
            for widget in self._rows:
                self.expander.add_row(widget)
        self.set_visible(bool(rows))
