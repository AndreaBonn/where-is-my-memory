"""S1: a "?" beside the hard words opens two lines in plain words."""

import pytest
from gi.repository import Gtk

from tests.ui.conftest import descendants
from wimm.ui.widgets import icon_only_label
from wimm.ui.widgets.summary import SummaryPanel

pytestmark = pytest.mark.ui


def help_buttons(panel: Gtk.Widget) -> dict[str, Gtk.MenuButton]:
    found = [w for w in descendants(panel) if isinstance(w, Gtk.MenuButton)]
    return {icon_only_label(button=b) or "": b for b in found}


def popover_text(button: Gtk.MenuButton) -> str:
    popover = button.get_popover()
    assert popover is not None
    labels = [w for w in descendants(popover) if isinstance(w, Gtk.Label)]
    return " ".join(label.get_label() for label in labels)


def test_memory_and_disk_titles_explain_themselves(display: None) -> None:
    buttons = help_buttons(SummaryPanel())

    assert set(buttons) >= {"Cos'è la memoria (RAM)?", "Cos'è lo spazio sul disco?"}
    assert "dove lavorano i programmi aperti" in popover_text(buttons["Cos'è la memoria (RAM)?"])
    assert "anche a computer spento" in popover_text(buttons["Cos'è lo spazio sul disco?"])
