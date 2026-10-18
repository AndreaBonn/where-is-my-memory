import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

SELECTION_SIGNAL = "notify::selection-bound"
CHANGED_SIGNAL = "changed"


def focus_at_end(*, row: Gtk.Widget, entry: Gtk.Entry) -> None:
    """Put the caret after the saved folders and bring their row into view.

    Deferred to idle: when the page shows it has no size to scroll yet, and Adwaita restores
    the focus with a plain ``grab_focus()``, which selects the whole text.
    """
    GLib.idle_add(_settle_focus, row, entry)


def _settle_focus(row: Gtk.Widget, entry: Gtk.Entry) -> bool:
    # A selected text would be erased by the first key press, with the roots already saved.
    entry.grab_focus_without_selecting()
    entry.set_position(-1)
    _guard_against_select_all(entry=entry)
    viewport = row.get_ancestor(Gtk.Viewport)
    if isinstance(viewport, Gtk.Viewport):
        viewport.scroll_to(row, None)
    return GLib.SOURCE_REMOVE


def _guard_against_select_all(*, entry: Gtk.Entry) -> None:
    """Undo, once, a select-all that lands after the caret was placed.

    Under load Adwaita's focus restore can run after the idle callback; the order is not
    under our control, so the outcome is enforced instead. The guard ends at the first
    collapse or at the first edit, so a later Ctrl+A by the user is left alone.
    """
    handlers: list[int] = []

    def release() -> None:
        for handler in handlers:
            entry.disconnect(handler)
        handlers.clear()

    def on_selection(*_args: object) -> None:
        text = entry.get_text()
        bounds = entry.get_selection_bounds()
        if text and bounds and (min(bounds), max(bounds)) == (0, len(text)):
            release()
            entry.set_position(-1)

    handlers.append(entry.connect(SELECTION_SIGNAL, on_selection))
    handlers.append(entry.connect(CHANGED_SIGNAL, lambda *_args: release()))
