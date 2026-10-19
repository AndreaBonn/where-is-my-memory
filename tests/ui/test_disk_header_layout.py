"""F29: the Disco header fits the window at 360 px with the selection controls shown."""

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import WindowFactory, descendants, main_context_iterate, wait_until
from tests.ui.disk_actions_helpers import setup
from tests.ui.disk_select_helpers import select_toggle
from wimm.ui.pages.disk_header import FREE_SELECTED_NAME, SAFE_BUTTON_NAME, SCAN_LABEL
from wimm.ui.window import MainWindow
from wimm.ui.window_state import MIN_WIDTH

pytestmark = pytest.mark.ui
LAYOUT_PASSES = 20


def _header(*, window: MainWindow) -> Adw.Clamp:
    window.view_stack.set_visible_child_name("disk")
    select_toggle(window.disk).set_active(True)
    for _ in range(LAYOUT_PASSES):
        main_context_iterate()
    clamps = [w for w in descendants(window.disk) if isinstance(w, Adw.Clamp)]
    (header,) = [
        c
        for c in clamps
        if SAFE_BUTTON_NAME in {w.get_name() for w in descendants(c) if isinstance(w, Gtk.Button)}
    ]
    # The check must see the full header: every control shown, nothing hidden to fit.
    shown = {w.get_name() for w in descendants(header) if w.get_mapped()}
    assert {SAFE_BUTTON_NAME, FREE_SELECTED_NAME} <= shown
    return header


def _scan_button(*, header: Adw.Clamp) -> Gtk.Button:
    (scan,) = [
        w for w in descendants(header) if isinstance(w, Gtk.Button) and w.get_label() == SCAN_LABEL
    ]
    return scan


def test_header_needs_no_more_than_the_narrowest_window(window_factory: WindowFactory) -> None:
    window, _service = setup(window_factory)
    header = _header(window=window)

    assert header.measure(Gtk.Orientation.HORIZONTAL, -1)[0] <= MIN_WIDTH


def test_scan_button_stays_inside_the_page_beside_the_texts(
    window_factory: WindowFactory,
) -> None:
    window, _service = setup(window_factory)
    header = _header(window=window)
    scan = _scan_button(header=header)
    # The page gets its width from a later layout pass: measure only once it has one.
    wait_until(
        lambda: window.disk.get_width() > 0 and scan.get_mapped(),
        description="the Disco page allocated with the scan button mapped",
    )

    found, bounds = scan.compute_bounds(window.disk)

    assert found and scan.get_mapped()
    assert bounds.get_x() + bounds.get_width() <= window.disk.get_width() + 1
    assert bounds.get_x() > window.disk.get_width() / 2
