"""T-6.24: the model removal row and its dialog title, in Italian and in English."""

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import report
from tests.ui.conftest import descendants
from tests.ui.test_disk_cache_items import HF_PATH, _hf_entry
from wimm.model.enums import ActionKind
from wimm.ui.dialogs.text import dialog_title
from wimm.ui.disk_view import build_disk_sections
from wimm.ui.pages.disk_rows import build_disk_row


def test_dialog_title_names_the_model() -> None:
    title = dialog_title(kind=ActionKind.CACHE_ITEM_REMOVE, subject="org/m0")

    assert title == "Rimuovere org/m0?"


@pytest.mark.usefixtures("english")
def test_dialog_title_in_english() -> None:
    title = dialog_title(kind=ActionKind.CACHE_ITEM_REMOVE, subject="org/m0")

    assert title == "Remove org/m0?"


@pytest.mark.ui
@pytest.mark.usefixtures("english", "display")
def test_sub_row_in_english() -> None:
    sections = build_disk_sections(report=report(caches=(_hf_entry(),)), min_age_days=90)
    row = next(r for s in sections for r in s.rows if r.subtitle == HF_PATH)
    widget = build_disk_row(row=row, on_action=lambda _r: None, buttons=[])

    sub = next(
        r for r in descendants(widget) if isinstance(r, Adw.ActionRow) and r.get_title() == "org/m0"
    )
    labels = [w.get_label() for w in descendants(sub) if isinstance(w, Gtk.Label)]
    buttons = [w.get_label() for w in descendants(sub) if isinstance(w, Gtk.Button)]
    assert buttons == ["Remove"]
    assert "Caution" in labels
