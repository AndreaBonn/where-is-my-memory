"""A toast that offers an action stays long enough to read it and decide."""

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Adw", "1")
from gi.repository import Adw

from wimm.ui.toasts import ACTION_TOAST_TIMEOUT_S, ToastNotifier

pytestmark = pytest.mark.ui
ADW_DEFAULT_TIMEOUT_S = 5


class RecordingOverlay:
    def __init__(self) -> None:
        self.toasts: list[Adw.Toast] = []

    def add_toast(self, toast: Adw.Toast) -> None:
        self.toasts.append(toast)


def test_a_toast_with_a_button_stays_longer_than_a_plain_one(display: None) -> None:
    overlay = RecordingOverlay()
    notify = ToastNotifier(overlay=overlay)

    notify("Fatto")
    notify("Fatto", button="Copia", on_button=lambda: None)

    plain, action = overlay.toasts
    assert plain.get_timeout() == ADW_DEFAULT_TIMEOUT_S
    assert action.get_timeout() == ACTION_TOAST_TIMEOUT_S > ADW_DEFAULT_TIMEOUT_S
