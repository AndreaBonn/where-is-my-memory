"""Children of a cache row that lists items: a model has badge and button, a rest row neither."""

from collections.abc import Callable

from gi.repository import Adw, Gtk

from wimm.ui.disk_model import DiskRowView
from wimm.ui.format import button_label
from wimm.ui.pages.disk_select import CheckFactory
from wimm.ui.widgets import ACCESSIBLE_LABEL_ATTR, color_primary
from wimm.ui.widgets.risk_badge import make_risk_badge

SIZE_SPACING = 6
RowAction = Callable[[DiskRowView], None]


def item_accessible_name(*, row: DiskRowView) -> str:
    """Title and size, then the row text: the path, then the consequence or the reason."""
    parts = (row.title, row.size_text, row.subtitle, row.consequence or row.note)
    return ". ".join(part for part in parts if part)


def item_subtitle(*, row: DiskRowView) -> str:
    """The path, then on its own line the consequence (with an action) or the reason (without)."""
    second = row.consequence or row.note
    return f"{row.subtitle}\n{second}" if second else row.subtitle


def _item_suffix(*, row: DiskRowView) -> Gtk.Box:
    """Size and badge on one line, the button (added by the caller) under them."""
    suffix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=SIZE_SPACING)
    suffix.set_valign(Gtk.Align.CENTER)
    info = Gtk.Box(spacing=SIZE_SPACING, halign=Gtk.Align.END)
    size = Gtk.Label(label=row.size_text, valign=Gtk.Align.BASELINE_CENTER)
    size.add_css_class("wimm-reclaim")
    info.append(size)
    if row.risk_text is not None and row.risk_style is not None:
        badge = make_risk_badge(text=row.risk_text, style=row.risk_style)
        badge.set_valign(Gtk.Align.BASELINE_CENTER)
        info.append(badge)
    suffix.append(info)
    return suffix


def _name_row(*, widget: Adw.ActionRow, row: DiskRowView) -> None:
    name = item_accessible_name(row=row)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [name])
    setattr(widget, ACCESSIBLE_LABEL_ATTR, name)


def _add_check(*, widget: Adw.ActionRow, row: DiskRowView, make_check: CheckFactory | None) -> None:
    check = None if make_check is None else make_check(row)
    if check is not None:
        widget.add_prefix(check)


def _add_button(
    *,
    suffix: Gtk.Box,
    row: DiskRowView,
    on_action: RowAction | None,
    buttons: list[Gtk.Button] | None,
) -> None:
    if on_action is None or row.action_kind is None or row.risk is None:
        return
    button = Gtk.Button(label=button_label(kind=row.action_kind), halign=Gtk.Align.END)
    color_primary(button=button, risk=row.risk)
    button.connect("clicked", lambda *_a: on_action(row))
    suffix.append(button)
    if buttons is not None:
        buttons.append(button)


def build_item_row(
    *,
    row: DiskRowView,
    on_action: RowAction | None = None,
    buttons: list[Gtk.Button] | None = None,
    make_check: CheckFactory | None = None,
) -> Adw.ActionRow:
    """A sub-row: title, text under it, size and badge on the right, "Rimuovi" for a model.

    The button is also appended to ``buttons`` so the section can disable it while an action runs.
    ``make_check`` gives the selection check box of the row, or None for a row that has none.
    """
    widget = Adw.ActionRow(
        title=row.title,
        subtitle=item_subtitle(row=row),
        use_markup=False,
        title_lines=2,
        subtitle_lines=0,
        tooltip_text=row.title,
    )
    _name_row(widget=widget, row=row)
    _add_check(widget=widget, row=row, make_check=make_check)
    suffix = _item_suffix(row=row)
    widget.add_suffix(suffix)
    _add_button(suffix=suffix, row=row, on_action=on_action, buttons=buttons)
    return widget


def build_more_row(*, text: str) -> Adw.ActionRow:
    """The "e altre N" line under the last sub-row."""
    return Adw.ActionRow(title=text, use_markup=False)


def item_children(
    *,
    row: DiskRowView,
    on_action: RowAction | None = None,
    buttons: list[Gtk.Button] | None = None,
    make_check: Callable[[DiskRowView | None], CheckFactory] | None = None,
) -> list[Adw.ActionRow]:
    """Every child row of a cache row, the counter last when the cap hid items.

    ``make_check(parent)`` gives the check maker of the sub-rows of the cache row ``parent``.
    """
    items_check = None if make_check is None else make_check(row)
    children = [
        build_item_row(row=item, on_action=on_action, buttons=buttons, make_check=items_check)
        for item in row.items
    ]
    if row.items_more:
        children.append(build_more_row(text=row.items_more))
    return children
