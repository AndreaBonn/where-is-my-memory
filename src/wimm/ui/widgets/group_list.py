from gi.repository import Gtk

from wimm.ui.widgets.group_row import GroupRowWidget

IDLE_HEADER = "Da liberare · non li usi da tempo"
OTHER_HEADER = "In uso adesso o non misurabile"
HEADER_MARGIN = 12


def build_list() -> Gtk.ListBox:
    listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listing.add_css_class("boxed-list")
    listing.set_sort_func(_by_rank)
    listing.set_header_func(_section_header)
    return listing


def _by_rank(first: Gtk.ListBoxRow, second: Gtk.ListBoxRow) -> int:
    """Order rows by the position the view model gave them (idle first, then reclaimable)."""
    if not (isinstance(first, GroupRowWidget) and isinstance(second, GroupRowWidget)):
        return 0
    return first.sort_rank - second.sort_rank


def _section_header(row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
    """P9: a title where the idle part starts and where the rest starts."""
    if not isinstance(row, GroupRowWidget):
        return
    starts = not isinstance(before, GroupRowWidget) or before.is_idle != row.is_idle
    if not starts:
        row.set_header(None)
        return
    label = Gtk.Label(label=IDLE_HEADER if row.is_idle else OTHER_HEADER, xalign=0)
    label.add_css_class("heading")
    label.add_css_class("dim-label")
    for side in ("top", "bottom", "start", "end"):
        getattr(label, f"set_margin_{side}")(HEADER_MARGIN)
    row.set_header(label)
