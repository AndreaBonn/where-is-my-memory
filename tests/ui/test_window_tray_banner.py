import pytest
from gi.repository import Gtk

from tests.ui.conftest import FakeSource, WindowFactory, descendants, present_and_settle
from wimm.model.snapshot import Snapshot
from wimm.ui.window import TRAY_MISSING_TEXT, MainWindow

pytestmark = pytest.mark.ui
BANNER_TEXT = "L'icona nella barra richiede l'estensione AppIndicator di Ubuntu"


def test_the_banner_is_hidden_until_the_tray_is_reported_missing(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    assert window.tray_banner.get_title() == TRAY_MISSING_TEXT == BANNER_TEXT
    assert not window.tray_banner.get_revealed()

    window.set_tray_missing(True)

    assert window.tray_banner.get_revealed()


def test_the_banner_goes_away_when_the_tray_host_appears(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.set_tray_missing(True)
    assert window.tray_banner.get_revealed()  # positive pair for the assertion below

    window.set_tray_missing(False)

    assert not window.tray_banner.get_revealed()


def menu_entries(window: MainWindow) -> dict[str, str]:
    """Label to action name of the main menu."""
    models = [w.get_menu_model() for w in descendants(window) if isinstance(w, Gtk.MenuButton)]
    entries: dict[str, str] = {}
    for menu in (m for m in models if m is not None):
        for index in range(menu.get_n_items()):
            label = menu.get_item_attribute_value(index, "label")
            action = menu.get_item_attribute_value(index, "action")
            if label is not None and action is not None:
                entries[label.get_string()] = action.get_string()
    return entries


def test_the_window_menu_has_the_quit_entry(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    entries = menu_entries(window)
    assert entries["Esci"] == "app.quit"
    assert "Voce inesistente" not in entries
