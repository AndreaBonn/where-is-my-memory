"""F11: every box in a Disco row measures the same height with and without a width.

GTK checks this on each layout and prints "reports a minimum height of 19, but minimum
height for width ... is 20. Expect overlapping widgets." for each row when it fails.
"""

from datetime import datetime

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import MB, cache, report
from tests.ui.conftest import descendants
from wimm.model.disk import CacheKind
from wimm.ui.pages.disk import DiskPage
from wimm.ui.widgets import install_style

pytestmark = pytest.mark.ui
# The width GTK's own check measures with.
UNBOUNDED_WIDTH = 1048576
MIN_AGE = 90


def min_height(widget: Gtk.Widget, *, for_width: int) -> int:
    return widget.measure(Gtk.Orientation.VERTICAL, for_width)[0]


def test_row_boxes_measure_one_minimum_height_at_any_width(display: None, now: datetime) -> None:
    install_style()
    page = DiskPage(on_rescan=lambda: None)
    page.show_report(
        report=report(caches=(cache(kind=CacheKind.GRADLE, size=2300 * MB),)),
        now=now,
        min_age_days=MIN_AGE,
    )
    window = Gtk.Window(child=page)
    window.present()

    rows = [w for w in descendants(page) if isinstance(w, Adw.ActionRow)]
    boxes = [w for row in rows for w in descendants(row) if isinstance(w, Gtk.Box)]
    badged = [b for b in boxes if any(w.has_css_class("wimm-badge") for w in descendants(b))]

    assert badged, "no row with a risk badge: the check would pass on nothing"
    mismatched = [
        (min_height(box, for_width=-1), min_height(box, for_width=UNBOUNDED_WIDTH))
        for box in boxes
        if min_height(box, for_width=-1) != min_height(box, for_width=UNBOUNDED_WIDTH)
    ]
    window.destroy()
    assert mismatched == []
