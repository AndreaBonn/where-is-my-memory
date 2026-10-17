import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from wimm.model.enums import Risk

ACTIONS_UNAVAILABLE_TOOLTIP = "Disponibile con le azioni (fase 3)"
NARROW_CLASS = "wimm-narrow"

# GTK 4.14 has no public getter for an accessible label: name_icon_button also keeps the
# label as a Python attribute on the wrapper, so tests can assert none is missing. PyGObject
# keeps a wrapper that carries Python state alive for the widget's lifetime, parenting included.
ACCESSIBLE_LABEL_ATTR = "wimm_accessible_label"
SUGGESTED_CLASS = "suggested-action"
SECONDARY_CLASS = "wimm-secondary"
ROW_CLASS = "wimm-row"

_STYLE = """
.wimm-bar { border-radius: 7px; background: alpha(currentColor, 0.08); }
.wimm-bar-segment { min-height: 14px; }
.wimm-swatch { min-width: 10px; min-height: 10px; border-radius: 3px; }
.wimm-seg-0 { background: @blue_3; }
.wimm-seg-1 { background: @green_4; }
.wimm-seg-2 { background: @orange_3; }
.wimm-seg-3 { background: @purple_3; }
.wimm-seg-4 { background: @red_5; }
.wimm-seg-5 { background: @yellow_5; }
.wimm-seg-6 { background: @red_3; }
.wimm-seg-7 { background: @brown_3; }
.wimm-seg-other { background: @brown_1; }
.wimm-seg-cache { background: @light_5; }
.wimm-seg-unattributed { background: @dark_2; }
.wimm-seg-free { background: alpha(currentColor, 0.14); }
.wimm-badge { padding: 1px 8px; border-radius: 8px; font-size: small; font-weight: 600; }
.wimm-badge.success { color: @success_color; background: alpha(@success_color, 0.16); }
.wimm-badge.warning { color: @warning_color; background: alpha(@warning_color, 0.16); }
.wimm-badge.error { color: @error_color; background: alpha(@error_color, 0.16); }
.wimm-badge.dim-label { background: alpha(currentColor, 0.08); }
.wimm-reclaim { font-weight: 600; }
.wimm-status { border-radius: 12px; padding: 12px 14px; }
.wimm-status.success { background: alpha(@success_color, 0.12); }
.wimm-status.warning { background: alpha(@warning_color, 0.16); }
.wimm-status.error { background: alpha(@error_color, 0.16); }
.wimm-warning { background: alpha(@warning_color, 0.14); border-radius: 8px; padding: 8px 12px; }
.wimm-facts { background: alpha(currentColor, 0.06); border-radius: 8px; padding: 8px 12px; }
/* S2: the lines that explain a decision; pt follows the system text size, px would not. */
.wimm-secondary, .wimm-row .subtitle { font-size: 10pt; }
"""
# S2: Adwaita dims these lines to 0.55; its high contrast mode already sets 0.9, so this
# stronger value is installed only outside it, never lowering a contrast the user chose.
_CONTRAST_STYLE = ".wimm-secondary.dim-label, .wimm-row .subtitle { opacity: 0.75; }"
_contrast = Gtk.CssProvider()
_contrast.load_from_string(_CONTRAST_STYLE)
_contrast_on: set[Gdk.Display] = set()

_installed_displays: set[Gdk.Display] = set()


def install_style() -> None:
    """Install the application CSS once per display."""
    display = Gdk.Display.get_default()
    if display is None or display in _installed_displays:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(_STYLE)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _installed_displays.add(display)
    manager = Adw.StyleManager.get_default()
    sync_contrast(high_contrast=manager.get_high_contrast())
    manager.connect(
        "notify::high-contrast", lambda m, *_a: sync_contrast(high_contrast=m.get_high_contrast())
    )


def sync_contrast(*, high_contrast: bool) -> None:
    """S2: the stronger secondary text only when the system is not in high contrast."""
    display = Gdk.Display.get_default()
    if display is None:
        return
    if high_contrast and display in _contrast_on:
        Gtk.StyleContext.remove_provider_for_display(display, _contrast)
        _contrast_on.discard(display)
    elif not high_contrast and display not in _contrast_on:
        Gtk.StyleContext.add_provider_for_display(
            display, _contrast, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        _contrast_on.add(display)


def contrast_installed() -> bool:
    """True while the stronger secondary text is in effect on the default display."""
    return Gdk.Display.get_default() in _contrast_on


def name_icon_button(*, button: Gtk.Button | Gtk.MenuButton, label: str) -> None:
    """Give an icon-only button its tooltip and accessible name (spec 10.4)."""
    button.set_tooltip_text(label)
    button.update_property([Gtk.AccessibleProperty.LABEL], [label])
    setattr(button, ACCESSIBLE_LABEL_ATTR, label)


def icon_only_label(*, button: Gtk.Button | Gtk.MenuButton) -> str | None:
    """The accessible name given through name_icon_button, if any."""
    return getattr(button, ACCESSIBLE_LABEL_ATTR, None)


def color_primary(*, button: Gtk.Button, risk: Risk) -> None:
    """S3: the next step of a row is blue when nothing is lost; otherwise it stays grey."""
    if risk is Risk.SAFE:
        button.add_css_class(SUGGESTED_CLASS)


def clear_children(*, container: Gtk.Box | Gtk.Grid) -> None:
    """Remove every child of a box or grid."""
    while (child := container.get_first_child()) is not None:
        container.remove(child)
