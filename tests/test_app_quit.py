import logging
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from gi.repository import Gio, GLib

from wimm import app
from wimm.tray import tray as tray_module


class Recorder:
    """Records the calls it receives, in order, under the name they were made with."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, (*args, *kwargs.items())))

        return record


def quit_target(*, held: bool) -> tuple[SimpleNamespace, list[str]]:
    order: list[str] = []
    target = SimpleNamespace(
        _held=held,
        release=lambda: order.append("release"),
        quit=lambda: order.append("quit"),
    )
    return target, order


def test_quit_releases_the_hold_once_then_quits_and_keeps_the_signal_source() -> None:
    target, order = quit_target(held=True)
    # GLib.SOURCE_CONTINUE: the signal handler stays installed.
    assert app._quit(application=target) is True
    assert order == ["release", "quit"]
    assert target._held is False


def test_a_second_quit_does_not_release_again() -> None:
    target, order = quit_target(held=True)
    app._quit(application=target)
    app._quit(application=target)
    assert order == ["release", "quit", "quit"]


def test_quit_without_a_hold_only_quits() -> None:
    target, order = quit_target(held=False)
    app._quit(application=target)
    assert order == ["quit"]


class FakeTray:
    instances: ClassVar[list["FakeTray"]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.on_missing: Any = None
        FakeTray.instances.append(self)

    def start(self, *, on_missing: Any) -> None:
        self.on_missing = on_missing


class FailingTray(FakeTray):
    def start(self, *, on_missing: Any) -> None:
        raise RuntimeError("no bus")


@pytest.fixture(autouse=True)
def reset_fake_tray() -> None:
    FakeTray.instances = []


def tray_application() -> tuple[SimpleNamespace, Recorder, Recorder]:
    host, application_calls = Recorder(), Recorder()
    application = SimpleNamespace(
        _service="the-service",
        _window_host=host,
        _tray=None,
        activate_action=lambda *args: application_calls.calls.append(("activate_action", args)),
    )
    return application, host, application_calls


def test_start_tray_wires_open_quit_and_missing_to_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tray_module, "Tray", FakeTray)
    application, host, application_calls = tray_application()
    app._start_tray(application, "the-connection")
    (tray,) = FakeTray.instances
    assert application._tray is tray
    assert tray.kwargs["connection"] == "the-connection"
    assert tray.kwargs["service"] == "the-service"
    tray.kwargs["on_open"]("id-api")
    assert host.calls == [("present", (("group_id", "id-api"),))]
    tray.kwargs["on_quit"]()
    assert application_calls.calls == [("activate_action", ("quit", None))]
    host.calls.clear()
    tray.on_missing(True)
    assert host.calls == [
        ("set_tray_missing", (("missing", True),)),
        ("present", (("group_id", None),)),
    ]


def test_start_tray_failure_is_logged_and_leaves_no_tray(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    application, _host, _calls = tray_application()
    monkeypatch.setattr(tray_module, "Tray", FailingTray)
    with caplog.at_level(logging.ERROR):
        app._start_tray(application, "the-connection")
    assert "Cannot show the tray icon" in caplog.text
    assert application._tray is None


def shutdown_target(*, service: object) -> tuple[SimpleNamespace, list[int]]:
    sources = [GLib.timeout_add_seconds(3600, lambda: GLib.SOURCE_CONTINUE) for _ in range(2)]
    target = SimpleNamespace(
        _service=service,
        _tray=Recorder(),
        _inspector=Recorder(),
        _signals=tuple(sources),
    )
    return target, sources


def source_is_alive(source: int) -> bool:
    return GLib.MainContext.default().find_source_by_id(source) is not None


@pytest.fixture
def gio_shutdown(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    seen: list[object] = []
    monkeypatch.setattr(Gio.Application, "do_shutdown", seen.append)
    return seen


def test_shutdown_stops_every_part_and_removes_the_signal_sources(
    gio_shutdown: list[object],
) -> None:
    service = Recorder()
    target, sources = shutdown_target(service=service)
    assert all(source_is_alive(source) for source in sources)
    app._shutdown(target)
    assert [name for name, _ in service.calls] == ["stop"]
    assert [name for name, _ in target._tray.calls] == ["close"]
    assert [name for name, _ in target._inspector.calls] == ["close"]
    assert not any(source_is_alive(source) for source in sources)
    assert gio_shutdown == [target]


def test_shutdown_without_a_service_still_closes_the_other_parts(
    gio_shutdown: list[object],
) -> None:
    target, sources = shutdown_target(service=None)
    app._shutdown(target)
    assert [name for name, _ in target._tray.calls] == ["close"]
    assert [name for name, _ in target._inspector.calls] == ["close"]
    assert not any(source_is_alive(source) for source in sources)
    assert gio_shutdown == [target]


def test_a_part_that_fails_to_release_does_not_stop_the_others(
    gio_shutdown: list[object], caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenService:
        def stop(self) -> None:
            raise RuntimeError("boom")

    target, _sources = shutdown_target(service=BrokenService())
    with caplog.at_level(logging.ERROR):
        app._shutdown(target)
    assert "Cannot release" in caplog.text
    assert [name for name, _ in target._tray.calls] == ["close"]
    assert gio_shutdown == [target]
