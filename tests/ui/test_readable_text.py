"""S2: the lines that explain a decision are readable and follow the system text size."""

from collections.abc import Iterator

import pytest
from gi.repository import Adw, Gtk, Pango

from tests.ui.conftest import descendants, main_context_iterate
from wimm.ui.widgets import (
    SECONDARY_CLASS,
    contrast_installed,
    install_style,
    sync_contrast,
)

pytestmark = pytest.mark.ui
MIN_SECONDARY_PX = 13
DPI_SCALE = 1024
DEFAULT_DPI = 96
LARGE_TEXT = 1.5


def size_px(label: Gtk.Label) -> float:
    font = label.get_pango_context().get_font_description()
    assert font is not None
    return font.get_size() / Pango.SCALE


@pytest.fixture
def secondary(display: None) -> Iterator[Gtk.Label]:
    install_style()
    label = Gtk.Label(label="Non lo usi da 5 ore")
    label.add_css_class(SECONDARY_CLASS)
    window = Gtk.Window(child=label)
    window.present()
    main_context_iterate()
    yield label
    window.destroy()


def test_a_decision_line_is_at_least_13_px(secondary: Gtk.Label) -> None:
    assert size_px(secondary) >= MIN_SECONDARY_PX


def test_a_decision_line_grows_with_large_text(secondary: Gtk.Label) -> None:
    settings = Gtk.Settings.get_default()
    assert settings is not None
    normal = size_px(secondary)
    dpi = settings.get_property("gtk-xft-dpi")
    # Relative to the dpi in use: the display under test is not always at 96.
    current = dpi if dpi > 0 else DEFAULT_DPI * DPI_SCALE
    try:
        settings.set_property("gtk-xft-dpi", int(current * LARGE_TEXT))
        main_context_iterate()
        assert size_px(secondary) == pytest.approx(normal * LARGE_TEXT, rel=0.05)
    finally:
        settings.set_property("gtk-xft-dpi", dpi)


def test_row_subtitles_are_decision_lines_too(display: None) -> None:
    install_style()
    row = Adw.ActionRow(title="whitebox", subtitle="Progetto · non in uso da 5 h")
    row.add_css_class("wimm-row")
    rows = Gtk.ListBox()
    rows.append(row)
    window = Gtk.Window(child=rows)
    window.present()
    main_context_iterate()
    (subtitle,) = [w for w in descendants(row) if w.has_css_class("subtitle")]
    assert isinstance(subtitle, Gtk.Label)

    assert size_px(subtitle) >= MIN_SECONDARY_PX
    window.destroy()


def test_more_contrast_only_when_the_system_is_not_already_high_contrast(display: None) -> None:
    install_style()
    try:
        sync_contrast(high_contrast=True)
        assert not contrast_installed()

        sync_contrast(high_contrast=False)
        assert contrast_installed()
    finally:
        sync_contrast(high_contrast=Adw.StyleManager.get_default().get_high_contrast())
