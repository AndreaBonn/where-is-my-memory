from types import SimpleNamespace

from wimm.app import _tray_missing


class FakeHost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_tray_missing(self, *, missing: bool) -> None:
        self.calls.append(("set_tray_missing", missing))

    def present(self, *, group_id: str | None) -> None:
        self.calls.append(("present", group_id))


def test_a_missing_tray_flags_the_banner_then_opens_the_window() -> None:
    host = FakeHost()
    _tray_missing(SimpleNamespace(_window_host=host), True)
    assert host.calls == [("set_tray_missing", True), ("present", None)]


def test_a_tray_that_is_back_only_clears_the_banner() -> None:
    host = FakeHost()
    _tray_missing(SimpleNamespace(_window_host=host), False)
    assert host.calls == [("set_tray_missing", False)]
