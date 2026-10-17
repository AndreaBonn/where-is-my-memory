import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import FakeSource, WindowFactory, descendants
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets.system_section import LOCK_ICON, SystemSection

pytestmark = pytest.mark.ui


def test_system_section_says_in_plain_words_that_nothing_here_can_be_broken(
    display: None, snapshot: Snapshot
) -> None:
    section = SystemSection()
    section.show_snapshot(snapshot=snapshot)

    assert section.get_visible()
    assert section.expander.get_title() == "Parti del sistema · 1,4 GB"
    assert "non puoi rompere niente" in (section.expander.get_subtitle() or "")
    assert not section.expander.get_expanded()


def test_every_system_row_carries_a_lock_and_no_button(display: None, snapshot: Snapshot) -> None:
    section = SystemSection()
    section.show_snapshot(snapshot=snapshot)

    # The expander draws its own header with an internal ActionRow: skip it.
    header = section.expander.get_title()
    rows = [
        w
        for w in descendants(section.expander)
        if isinstance(w, Adw.ActionRow) and w.get_title() != header
    ]
    assert len(rows) == section.row_count >= 1
    assert "Sessione GNOME" in [row.get_title() for row in rows]
    for row in rows:
        icons = [w.get_icon_name() for w in descendants(row) if isinstance(w, Gtk.Image)]
        assert LOCK_ICON in icons
    assert not [w for w in descendants(section) if isinstance(w, Gtk.Button)]


def test_section_is_hidden_while_waiting(display: None, snapshot: Snapshot) -> None:
    section = SystemSection()
    section.show_snapshot(snapshot=snapshot)
    section.show_waiting()
    assert not section.get_visible()


def test_window_has_two_tabs_and_the_system_list_inside_the_panoramica(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))

    stack = window.view_stack
    assert stack.get_child_by_name("overview") is window.overview
    assert stack.get_child_by_name("disk") is window.disk
    assert stack.get_child_by_name("system") is None
    assert window.system.is_ancestor(window.overview)
    assert window.system.row_count == 1
