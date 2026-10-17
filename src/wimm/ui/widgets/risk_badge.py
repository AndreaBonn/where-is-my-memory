from gi.repository import Gtk

BADGE_CLASS = "wimm-badge"
# The badge says the consequence too (P8): it wraps instead of crushing the row title.
BADGE_MAX_CHARS = 24
# Without a minimum a suffix gets one word per line even where there is room.
BADGE_MIN_CHARS = 12


def make_risk_badge(*, text: str, style: str) -> Gtk.Label:
    """Return a pill label: risk is always text, the style class only reinforces it."""
    badge = Gtk.Label(
        label=text,
        valign=Gtk.Align.CENTER,
        wrap=True,
        max_width_chars=BADGE_MAX_CHARS,
        width_chars=BADGE_MIN_CHARS,
        justify=Gtk.Justification.CENTER,
    )
    badge.add_css_class(BADGE_CLASS)
    badge.add_css_class(style)
    return badge


def update_risk_badge(*, badge: Gtk.Label, text: str, style: str) -> None:
    """Change text and style class of a badge made by make_risk_badge."""
    badge.set_label(text)
    for name in ("success", "warning", "error", "dim-label"):
        badge.remove_css_class(name)
    badge.add_css_class(style)
