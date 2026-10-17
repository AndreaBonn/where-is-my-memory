import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import descendants
from wimm.model.snapshot import Snapshot
from wimm.ui.pages.system import LOCK_ICON, SystemPage

pytestmark = pytest.mark.ui


def test_system_page_says_in_plain_words_that_nothing_here_can_be_broken(
    display: None, snapshot: Snapshot
) -> None:
    page = SystemPage()
    page.show_snapshot(snapshot=snapshot)

    texts = [w.get_label() for w in descendants(page) if isinstance(w, Gtk.Label)]
    assert any("non puoi rompere niente" in text for text in texts)
    assert not any("restano fuori dalla Panoramica" in text for text in texts)


def test_every_system_row_carries_a_lock(display: None, snapshot: Snapshot) -> None:
    page = SystemPage()
    page.show_snapshot(snapshot=snapshot)

    rows = [w for w in descendants(page) if isinstance(w, Adw.ActionRow)]
    assert len(rows) == page.row_count >= 1
    for row in rows:
        icons = [w.get_icon_name() for w in descendants(row) if isinstance(w, Gtk.Image)]
        assert LOCK_ICON in icons
