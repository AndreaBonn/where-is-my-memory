"""S1: a small "?" that opens a short explanation of a word in plain language."""

from gi.repository import Gtk

from . import name_icon_button

HELP_LABEL = "?"
POPOVER_WIDTH_CHARS = 40
POPOVER_MARGIN = 6
TITLE_SPACING = 4


def help_button(*, question: str, answer: str) -> Gtk.MenuButton:
    """The "?" button; ``question`` is its accessible name and tooltip."""
    text = Gtk.Label(label=answer, wrap=True, xalign=0, max_width_chars=POPOVER_WIDTH_CHARS)
    for side in ("top", "bottom", "start", "end"):
        getattr(text, f"set_margin_{side}")(POPOVER_MARGIN)
    # A child label, not `label`: a labelled MenuButton draws a dropdown arrow.
    button = Gtk.MenuButton(child=Gtk.Label(label=HELP_LABEL), popover=Gtk.Popover(child=text))
    button.add_css_class("flat")
    button.add_css_class("circular")
    button.set_valign(Gtk.Align.CENTER)
    name_icon_button(button=button, label=question)
    return button


def titled_with_help(*, title: Gtk.Widget, question: str, answer: str) -> Gtk.Box:
    """``title`` followed by its "?"."""
    box = Gtk.Box(spacing=TITLE_SPACING)
    box.append(title)
    box.append(help_button(question=question, answer=answer))
    return box
