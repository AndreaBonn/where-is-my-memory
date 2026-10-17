from gi.repository import Gtk

from wimm.ui.widgets.group_row import GroupRowWidget


def build_list() -> Gtk.ListBox:
    listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listing.add_css_class("boxed-list")
    listing.set_sort_func(_by_rank)
    return listing


def _by_rank(first: Gtk.ListBoxRow, second: Gtk.ListBoxRow) -> int:
    """Order rows by the position the view model gave them (reclaimable, name, id)."""
    if not (isinstance(first, GroupRowWidget) and isinstance(second, GroupRowWidget)):
        return 0
    return first.sort_rank - second.sort_rank
