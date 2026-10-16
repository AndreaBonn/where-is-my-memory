from gi.repository import Adw, Gtk

from wimm.model.snapshot import Snapshot
from wimm.ui.viewmodel import build_system_rows
from wimm.ui.views import SystemRow
from wimm.ui.widgets.state_views import LoadingView

MAX_CONTENT_WIDTH = 800
PAGE_MARGIN = 12
INTRO_TEXT = (
    "Questi processi servono al sistema o al desktop e restano fuori dalla Panoramica: "
    "qui sono solo elencati, senza azioni."
)
EMPTY_TITLE = "Nessun processo protetto"
STATE_LOADING = "loading"
STATE_LIST = "list"
STATE_EMPTY = "empty"


def _row_widget(*, row: SystemRow) -> Adw.ActionRow:
    widget = Adw.ActionRow(
        title=row.label,
        subtitle=row.reason,
        use_markup=False,
        title_lines=1,
        subtitle_lines=0,
    )
    memory = Gtk.Label(label=row.memory, valign=Gtk.Align.CENTER)
    memory.add_css_class("wimm-reclaim")
    widget.add_suffix(memory)
    return widget


class SystemPage(Gtk.Stack):
    """Sistema: read-only list of the protected groups with the reason (RF-07)."""

    def __init__(self) -> None:
        super().__init__()
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._empty = Adw.StatusPage(title=EMPTY_TITLE, icon_name="emblem-ok-symbolic")
        self._last: tuple[SystemRow, ...] | None = None
        intro = Gtk.Label(label=INTRO_TEXT, xalign=0, wrap=True)
        intro.add_css_class("dim-label")
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=PAGE_MARGIN,
            margin_top=PAGE_MARGIN,
            margin_bottom=PAGE_MARGIN,
            margin_start=PAGE_MARGIN,
            margin_end=PAGE_MARGIN,
        )
        box.append(intro)
        box.append(self._list)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(Adw.Clamp(maximum_size=MAX_CONTENT_WIDTH, child=box))
        self.add_named(LoadingView().page, STATE_LOADING)
        self.add_named(scroller, STATE_LIST)
        self.add_named(self._empty, STATE_EMPTY)
        self.set_visible_child_name(STATE_LOADING)

    @property
    def row_count(self) -> int:
        """Number of rows listed."""
        return len(self._last or ())

    def show_waiting(self) -> None:
        """Show the loading page until the first snapshot arrives."""
        self.set_visible_child_name(STATE_LOADING)

    def show_snapshot(self, *, snapshot: Snapshot) -> None:
        """List the protected groups, largest first."""
        rows = build_system_rows(snapshot=snapshot)
        if rows != self._last:
            self._last = rows
            self._list.remove_all()
            for row in rows:
                self._list.append(_row_widget(row=row))
        self.set_visible_child_name(STATE_LIST if rows else STATE_EMPTY)
