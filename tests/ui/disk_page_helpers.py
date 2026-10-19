from datetime import datetime
from pathlib import Path

from gi.repository import Gtk

from tests.ui.conftest import descendants
from wimm.model.disk import DiskReport
from wimm.ui.pages.disk import DiskPage
from wimm.ui.pages.disk_header import SAFE_BUTTON_NAME

SAMPLE = Path(__file__).parents[1] / "fixtures" / "disk_report_sample.json"
MIN_AGE = 90


def make_page(*, calls: list[str] | None = None) -> DiskPage:
    sink = calls if calls is not None else []
    return DiskPage(on_rescan=lambda: sink.append("rescan"))


def labels(widget: Gtk.Widget) -> list[str]:
    """The text each label shows, after markup parsing (``get_label`` returns the source)."""
    return [w.get_text() for w in descendants(widget) if isinstance(w, Gtk.Label)]


def scan_button(page: DiskPage) -> Gtk.Button:
    buttons = (w for w in descendants(page) if isinstance(w, Gtk.Button))
    return next(b for b in buttons if b.get_label() == "Controlla ora")


def show(page: DiskPage, *, report_: DiskReport | None, now: datetime) -> None:
    page.show_report(report=report_, now=now, min_age_days=MIN_AGE)


def buttons_in(widget: Gtk.Widget) -> list[Gtk.Button]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.Button)]


def safe_button(page: DiskPage) -> Gtk.Button:
    (button,) = [b for b in buttons_in(page) if b.get_name() == SAFE_BUTTON_NAME]
    return button
