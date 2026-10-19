"""The children of a cache row that lists items: one plain row per item, no action, no badge."""

from gi.repository import Adw, Gtk

from wimm.ui.disk_model import DiskRowView
from wimm.ui.widgets import ACCESSIBLE_LABEL_ATTR

SIZE_SPACING = 6


def item_accessible_name(*, row: DiskRowView) -> str:
    """Title and size, then the row text: the path of a model or what a rest row means."""
    return ". ".join(part for part in (row.title, row.size_text, row.subtitle) if part)


def build_item_row(*, row: DiskRowView) -> Adw.ActionRow:
    """A sub-row: title, text under it, size on the right; never a button or a badge."""
    widget = Adw.ActionRow(
        title=row.title,
        subtitle=row.subtitle,
        use_markup=False,
        title_lines=2,
        subtitle_lines=0,
        tooltip_text=row.title,
    )
    name = item_accessible_name(row=row)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [name])
    setattr(widget, ACCESSIBLE_LABEL_ATTR, name)
    size = Gtk.Label(label=row.size_text, valign=Gtk.Align.CENTER)
    size.add_css_class("wimm-reclaim")
    widget.add_suffix(size)
    return widget


def build_more_row(*, text: str) -> Adw.ActionRow:
    """The "e altre N" line under the last sub-row."""
    return Adw.ActionRow(title=text, use_markup=False)


def item_children(*, row: DiskRowView) -> list[Adw.ActionRow]:
    """Every child row of a cache row, the counter last when the cap hid items."""
    children = [build_item_row(row=item) for item in row.items]
    if row.items_more:
        children.append(build_more_row(text=row.items_more))
    return children
