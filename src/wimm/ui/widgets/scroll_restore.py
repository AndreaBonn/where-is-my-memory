from gi.repository import GLib, Gtk


class ScrollRestore:
    """Puts a scrolled list back where it was once a rebuild ends, unless someone moved it."""

    def __init__(self, *, scroller: Gtk.ScrolledWindow) -> None:
        self._scroller = scroller
        self.source = 0

    def queue(self, *, position: float) -> None:
        """Restore ``position`` at the next idle, replacing a pending restore."""
        self.cancel()
        expected = self._scroller.get_vadjustment().get_value()
        self.source = GLib.idle_add(self._restore, position, expected)

    def cancel(self) -> None:
        """Drop the pending restore, if any."""
        if self.source:
            GLib.source_remove(self.source)
            self.source = 0

    def _restore(self, position: float, expected: float) -> bool:
        self.source = 0
        adjustment = self._scroller.get_vadjustment()
        # A moved value means something else (the user, a focus change) scrolled meanwhile.
        if adjustment.get_value() == expected:
            adjustment.set_value(position)
        return GLib.SOURCE_REMOVE
