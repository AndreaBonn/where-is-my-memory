"""Shared fixtures of the Disco multiple-selection tests (S16, S17)."""

from datetime import datetime

from gi.repository import Gtk

from tests.core.disk_helpers import MB, cache, docker_disk, report, volume
from tests.ui.conftest import descendants
from tests.ui.test_disk_cache_items import _hf_entry
from wimm.model.disk import CacheKind, DiskReport
from wimm.ui.pages.disk import DiskPage
from wimm.ui.pages.disk_header import FREE_SELECTED_NAME, SELECT_TOGGLE_NAME

NOW = datetime.fromisoformat("2026-10-16T05:12:00+02:00")
MIN_AGE = 90
UV_ENTRY = "cache_clean|uv"
HF_ENTRY = "cache_clean|huggingface"
MODEL_0 = "cache_item_remove|huggingface:models--org--m0"
MODEL_1 = "cache_item_remove|huggingface:models--org--m1"
DANGER_ENTRY = "volume_remove|pgdata"
UV_SIZE = 2 * MB


def selection_report() -> DiskReport:
    return report(
        docker=docker_disk(volumes=(volume(name="pgdata"),)),
        caches=(_hf_entry(), cache(kind=CacheKind.UV, size=UV_SIZE, ino=12)),
    )


def make_page(*, picked: list[frozenset[str]] | None = None) -> DiskPage:
    sink = picked if picked is not None else []
    page = DiskPage(
        on_rescan=lambda: None,
        on_action=lambda _row: None,
    )
    page.set_selection_handler(sink.append)
    page.show_report(report=selection_report(), now=NOW, min_age_days=MIN_AGE)
    return page


def checks(page: DiskPage) -> dict[str, Gtk.CheckButton]:
    found = [w for w in descendants(page) if isinstance(w, Gtk.CheckButton)]
    return {c.get_name(): c for c in found}


def named_button(page: DiskPage, name: str) -> Gtk.Button | Gtk.ToggleButton:
    (button,) = [
        w
        for w in descendants(page)
        if isinstance(w, Gtk.Button | Gtk.ToggleButton) and w.get_name() == name
    ]
    return button


def select_toggle(page: DiskPage) -> Gtk.ToggleButton:
    button = named_button(page, SELECT_TOGGLE_NAME)
    assert isinstance(button, Gtk.ToggleButton)
    return button


def free_selected(page: DiskPage) -> Gtk.Button:
    button = named_button(page, FREE_SELECTED_NAME)
    assert isinstance(button, Gtk.Button)
    return button
