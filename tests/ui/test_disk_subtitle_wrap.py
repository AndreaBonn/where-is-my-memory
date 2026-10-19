"""S4 (RF-29): at 360 px a Disco row shows its whole consequence, never an ellipsis."""

from datetime import datetime

import pytest
from gi.repository import Adw, GLib, Gtk

from tests.core.disk_helpers import cache, docker_disk, image, report
from tests.ui.conftest import descendants
from wimm.model.disk import CacheKind
from wimm.ui.pages.disk import DiskPage
from wimm.ui.widgets import install_style

pytestmark = pytest.mark.ui
NARROW_WIDTH = 360
TALL_HEIGHT = 4000
MIN_AGE = 90
LAYOUT_ITERATIONS = 200
# The old cap: the longest consequences need more lines than this at 360 px.
OLD_SUBTITLE_CAP = 4


def subtitles_at_narrow_width() -> list[Gtk.Label]:
    install_style()
    page = DiskPage(on_rescan=lambda: None)
    docker = docker_disk(images=(image(char="c", tags=(), dangling=True),))
    page.show_report(
        report=report(docker=docker, caches=(cache(kind=CacheKind.MAVEN),)),
        now=datetime.fromisoformat("2026-10-19T12:00:00+02:00"),
        min_age_days=MIN_AGE,
    )
    window = Gtk.Window(child=page, default_width=NARROW_WIDTH, default_height=TALL_HEIGHT)
    window.present()
    context = GLib.MainContext.default()
    for _ in range(LAYOUT_ITERATIONS):
        context.iteration(False)
    rows = [w for w in descendants(page) if isinstance(w, Adw.ActionRow)]
    return [
        w
        for row in rows
        for w in descendants(row)
        if isinstance(w, Gtk.Label) and w.has_css_class("subtitle") and w.get_label()
    ]


def test_long_consequences_wrap_whole_at_360_px(display: None) -> None:
    subtitles = subtitles_at_narrow_width()

    assert subtitles, "no row subtitle found: the check would pass on nothing"
    lines = [label.get_layout().get_line_count() for label in subtitles]
    assert max(lines) > OLD_SUBTITLE_CAP, "no subtitle needs more lines than the old cap"
    assert [label.get_label() for label in subtitles if label.get_layout().is_ellipsized()] == []
