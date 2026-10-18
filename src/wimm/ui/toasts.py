from collections.abc import Callable
from typing import Protocol

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib

# A toast with an action carries a sentence to read and a decision to take: the default
# 5 s of Adw.Toast ran out before a user (and a click-through) could press the button.
ACTION_TOAST_TIMEOUT_S = 15


class ToastSink(Protocol):
    """The one call the notifier needs; ``Adw.ToastOverlay`` satisfies it."""

    def add_toast(self, toast: Adw.Toast) -> None: ...


class ToastNotifier:
    """Shows one toast at a time on an overlay; a new toast replaces the one on screen."""

    def __init__(self, *, overlay: ToastSink) -> None:
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
            toast.set_timeout(ACTION_TOAST_TIMEOUT_S)
            toast.connect("button-clicked", lambda *_args: on_button())
        self._current = toast
        self._overlay.add_toast(toast)


# How long a copied command stays on the clipboard before it is wiped.
CLIPBOARD_CLEAR_SECONDS = 60
TEXT_MIME_TYPE = "text/plain;charset=utf-8"
# Clipboard managers that honour it (Klipper and others) do not record the entry in history.
CLIPBOARD_HINT_MIME_TYPE = "x-kde-passwordManagerHint"
PASSWORD_HINT_VALUE = b"secret"

Scheduler = Callable[[int, Callable[[], bool]], int]


class ClearableClipboard(Protocol):
    """The two calls the wipe needs; ``Gdk.Clipboard`` satisfies it."""

    def is_local(self) -> bool: ...

    def set_content(self, provider: Gdk.ContentProvider | None) -> bool: ...


def clear_if_local(*, clipboard: ClearableClipboard) -> bool:
    """Empty ``clipboard`` if it still holds what this process put there; never repeats."""
    if clipboard.is_local():
        clipboard.set_content(None)
    return GLib.SOURCE_REMOVE


def copy_to_clipboard(*, text: str, schedule: Scheduler = GLib.timeout_add_seconds) -> bool:
    """Put ``text`` on the clipboard of the default display, flagged as secret, then wipe it.

    False when there is no display or the text cannot be encoded (a lone surrogate from a
    command line that is not valid UTF-8); nothing is copied or scheduled then.
    """
    display = Gdk.Display.get_default()
    if display is None:
        return False
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    content = Gdk.ContentProvider.new_union(
        [
            Gdk.ContentProvider.new_for_bytes(TEXT_MIME_TYPE, GLib.Bytes.new(data)),
            Gdk.ContentProvider.new_for_bytes(
                CLIPBOARD_HINT_MIME_TYPE, GLib.Bytes.new(PASSWORD_HINT_VALUE)
            ),
        ]
    )
    clipboard = display.get_clipboard()
    clipboard.set_content(content)
    schedule(CLIPBOARD_CLEAR_SECONDS, lambda: clear_if_local(clipboard=clipboard))
    return True
