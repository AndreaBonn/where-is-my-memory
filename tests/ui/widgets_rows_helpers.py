from datetime import datetime

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import descendants, main_context_iterate
from wimm.model.snapshot import Snapshot
from wimm.ui.viewmodel import build_rows
from wimm.ui.views import GroupRow, RowFilters
from wimm.ui.widgets import install_style
from wimm.ui.widgets.group_row import GroupRowWidget


@pytest.fixture
def group_row(display: None, snapshot: Snapshot, now: datetime) -> GroupRow:
    install_style()
    return build_rows(snapshot=snapshot, filters=RowFilters(), now=now)[0]


def labels_under(widget: Gtk.Widget) -> list[Gtk.Label]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.Label)]


def open_in_window(widget: GroupRowWidget) -> Gtk.Window:
    window = Gtk.Window(default_width=900, default_height=700)
    box = Gtk.ListBox()
    box.append(widget)
    window.set_child(box)
    window.present()
    main_context_iterate()
    return window


def member_row_named(widget: GroupRowWidget, name: str) -> Adw.ActionRow:
    return next(
        w for w in descendants(widget) if isinstance(w, Adw.ActionRow) and w.get_title() == name
    )


def member_menu(row: Adw.ActionRow) -> Gtk.MenuButton:
    return next(
        w
        for w in descendants(row)
        if isinstance(w, Gtk.MenuButton) and w.get_icon_name() is not None
    )


def with_first_member_memory(group_row: GroupRow, memory: str) -> GroupRow:
    from dataclasses import replace

    first = replace(group_row.members[0], memory=memory)
    return replace(group_row, members=(first, *group_row.members[1:]))


def focus_is_inside(*, window: Gtk.Window, button: Gtk.MenuButton) -> bool:
    """MenuButton hands the focus to its inner toggle, so test the button or a descendant."""
    focus = window.get_focus()
    return focus is not None and (focus is button or focus.is_ancestor(button))
