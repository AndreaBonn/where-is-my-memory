"""F14: the copy helper puts the text on the clipboard, flagged secret, and clears it later."""

from collections.abc import Callable

import pytest

from tests.ui.conftest import main_context_iterate
from wimm.ui.toasts import clear_if_local, copy_to_clipboard

gi = pytest.importorskip("gi")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio

pytestmark = pytest.mark.ui
ITERATIONS = 200
HINT = "x-kde-passwordManagerHint"


def test_copy_to_clipboard_makes_the_text_readable_back() -> None:
    assert copy_to_clipboard(text="cd '/a b' && node x.js\ncd /c && y") is True
    display = Gdk.Display.get_default()
    assert display is not None
    clipboard = display.get_clipboard()
    read: list[str | None] = []

    def done(source: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
        read.append(source.read_text_finish(result))

    clipboard.read_text_async(None, done)
    for _ in range(ITERATIONS):
        if read:
            break
        main_context_iterate()

    assert read == ["cd '/a b' && node x.js\ncd /c && y"]


class ScheduledTimers:
    """Stands in for ``GLib.timeout_add_seconds``: records the call, never waits."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, Callable[[], bool]]] = []

    def __call__(self, seconds: int, callback: Callable[[], bool]) -> int:
        self.calls.append((seconds, callback))
        return len(self.calls)


class FakeClipboard:
    def __init__(self, *, local: bool) -> None:
        self._local = local
        self.contents: list[object] = []

    def is_local(self) -> bool:
        return self._local

    def set_content(self, provider: object) -> bool:
        self.contents.append(provider)
        return True


def default_clipboard() -> Gdk.Clipboard:
    display = Gdk.Display.get_default()
    assert display is not None
    return display.get_clipboard()


def test_copy_flags_the_content_as_secret_for_clipboard_managers() -> None:
    assert copy_to_clipboard(text="cd -- /a && x", schedule=ScheduledTimers()) is True

    formats = default_clipboard().get_formats()
    assert formats.contain_mime_type(HINT)
    assert formats.contain_mime_type("text/plain;charset=utf-8")


def test_copy_schedules_the_clearing_after_one_minute() -> None:
    timers = ScheduledTimers()

    copy_to_clipboard(text="cd -- /a && x", schedule=timers)

    assert [seconds for seconds, _callback in timers.calls] == [60]


def test_the_scheduled_callback_empties_our_clipboard_and_stops() -> None:
    timers = ScheduledTimers()
    copy_to_clipboard(text="cd -- /a && x", schedule=timers)
    assert default_clipboard().is_local()

    again = timers.calls[0][1]()

    assert again is False
    assert not default_clipboard().get_formats().contain_mime_type("text/plain;charset=utf-8")


def test_clearing_empties_the_clipboard_when_the_content_is_still_ours() -> None:
    clipboard = FakeClipboard(local=True)

    assert clear_if_local(clipboard=clipboard) is False

    assert clipboard.contents == [None]


def test_clearing_leaves_alone_what_someone_else_copied_meanwhile() -> None:
    clipboard = FakeClipboard(local=False)

    assert clear_if_local(clipboard=clipboard) is False

    assert clipboard.contents == []


def test_copy_of_text_that_cannot_be_encoded_fails_without_raising_or_scheduling() -> None:
    timers = ScheduledTimers()

    assert copy_to_clipboard(text="node \udcff.js", schedule=timers) is False

    assert timers.calls == []
