from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw


class ToastNotifier:
    """Shows one toast at a time on an overlay; a new toast replaces the one on screen."""

    def __init__(self, *, overlay: Adw.ToastOverlay) -> None:
        self._overlay = overlay
        self._current: Adw.Toast | None = None

    def __call__(
        self, text: str, *, button: str | None = None, on_button: Callable[[], None] | None = None
    ) -> None:
        """Show ``text``; with ``button`` the toast carries an action that runs ``on_button``."""
        if self._current is not None:
            self._current.dismiss()
        toast = Adw.Toast(title=text, use_markup=False)
        if button is not None and on_button is not None:
            toast.set_button_label(button)
            toast.connect("button-clicked", lambda *_args: on_button())
        self._current = toast
        self._overlay.add_toast(toast)
