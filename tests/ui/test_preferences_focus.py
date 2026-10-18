"""The caret after the saved folders survives one select-all, and only one."""

import pytest
from gi.repository import Gtk

from tests.ui.conftest import main_context_iterate
from wimm.ui.dialogs.preferences_focus import focus_at_end

pytestmark = pytest.mark.ui
SAVED = "/home/u/code, /home/u/work"


def _settled_entry() -> Gtk.Entry:
    entry = Gtk.Entry(text=SAVED)
    window = Gtk.Window(child=entry)
    window.present()
    focus_at_end(row=entry, entry=entry)
    main_context_iterate()
    return entry


def test_a_select_all_after_the_caret_is_placed_is_undone(display: None) -> None:
    entry = _settled_entry()

    # What Adwaita's late focus restore does; select_region needs no window manager.
    entry.select_region(0, -1)

    assert not entry.get_selection_bounds()
    assert entry.get_position() == len(SAVED)


def test_the_guard_ends_at_its_first_collapse_so_a_later_select_all_stays(
    display: None,
) -> None:
    entry = _settled_entry()
    entry.select_region(0, -1)

    entry.select_region(0, -1)

    assert entry.get_selection_bounds() == (0, len(SAVED))


def test_the_guard_ends_at_the_first_edit(display: None) -> None:
    entry = _settled_entry()
    entry.set_text(SAVED + ", /x")

    entry.select_region(0, -1)

    assert entry.get_selection_bounds() == (0, len(SAVED) + len(", /x"))
