from gi.repository import Gtk

BADGE_CLASS = "wimm-badge"


def make_risk_badge(*, text: str, style: str) -> Gtk.Label:
    """Return a pill label: risk is always text, the style class only reinforces it."""
    badge = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    badge.add_css_class(BADGE_CLASS)
    badge.add_css_class(style)
    return badge


def update_risk_badge(*, badge: Gtk.Label, text: str, style: str) -> None:
    """Change text and style class of a badge made by make_risk_badge."""
    badge.set_label(text)
    for name in ("success", "warning", "error", "dim-label"):
        badge.remove_css_class(name)
    badge.add_css_class(style)
