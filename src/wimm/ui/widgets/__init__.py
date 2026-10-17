import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, Gtk

ACTIONS_UNAVAILABLE_TOOLTIP = "Disponibile con le azioni (fase 3)"
NARROW_CLASS = "wimm-narrow"

# GTK 4.14 has no public getter for an accessible label: name_icon_button also keeps the
# label as a Python attribute on the wrapper, so tests can assert none is missing. PyGObject
# keeps a wrapper that carries Python state alive for the widget's lifetime, parenting included.
ACCESSIBLE_LABEL_ATTR = "wimm_accessible_label"

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
.wimm-seg-cache { background: @light_5; }
.wimm-seg-unattributed { background: @dark_2; }
.wimm-seg-free { background: alpha(currentColor, 0.14); }
.wimm-badge { padding: 1px 8px; border-radius: 999px; font-size: small; font-weight: 600; }
.wimm-badge.success { color: @success_color; background: alpha(@success_color, 0.16); }
.wimm-badge.warning { color: @warning_color; background: alpha(@warning_color, 0.16); }
.wimm-badge.error { color: @error_color; background: alpha(@error_color, 0.16); }
.wimm-badge.dim-label { background: alpha(currentColor, 0.08); }
.wimm-reclaim { font-weight: 600; }
.wimm-warning { background: alpha(@warning_color, 0.14); border-radius: 8px; padding: 8px 12px; }
"""

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


def name_icon_button(*, button: Gtk.Button | Gtk.MenuButton, label: str) -> None:
    """Give an icon-only button its tooltip and accessible name (spec 10.4)."""
    button.set_tooltip_text(label)
    button.update_property([Gtk.AccessibleProperty.LABEL], [label])
    setattr(button, ACCESSIBLE_LABEL_ATTR, label)


def icon_only_label(*, button: Gtk.Button | Gtk.MenuButton) -> str | None:
    """The accessible name given through name_icon_button, if any."""
    return getattr(button, ACCESSIBLE_LABEL_ATTR, None)


def clear_children(*, container: Gtk.Box | Gtk.Grid) -> None:
    """Remove every child of a box or grid."""
    while (child := container.get_first_child()) is not None:
        container.remove(child)
