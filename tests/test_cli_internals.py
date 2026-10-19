import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.cli_helpers import SUBPROCESS_TIMEOUT_SECONDS, SUCCESS
from tests.test_cli import RecordingWindow


@pytest.mark.parametrize(
    "options,welcomed,expected",
    [
        ({}, True, [None]),
        ({"group": "example"}, True, ["example"]),
        ({"background": True}, True, []),
        ({"background": True}, False, [None]),
    ],
)
def test_command_line_routes_window_requests(
    options: dict[str, str | bool], welcomed: bool, expected: list[str | None], tmp_path: Path
) -> None:
    from gi.repository import GLib

    from wimm.app import _activate, _command_line
    from wimm.first_run import mark_welcomed

    if welcomed:
        mark_welcomed(state_dir=tmp_path)

    presented: list[str | None] = []
    variants = {
        key: GLib.Variant("b" if isinstance(value, bool) else "s", value)
        for key, value in options.items()
    }
    command_line = SimpleNamespace(
        get_options_dict=lambda: SimpleNamespace(lookup_value=lambda key, _: variants.get(key))
    )
    application = SimpleNamespace(
        _service=object(),
        _state_dir=tmp_path,
        _window_host=SimpleNamespace(present=lambda group_id: presented.append(group_id)),
    )
    application.activate = lambda: _activate(application=application)
    assert _command_line(application=application, command_line=command_line) == SUCCESS
    assert presented == expected


def test_command_line_reports_failed_service_startup() -> None:
    from wimm.app import STARTUP_FAILED, _command_line

    assert (
        _command_line(application=SimpleNamespace(_service=None), command_line=None)
        == STARTUP_FAILED
    )


def test_graphics_defaults_disable_gl_only_when_unset() -> None:
    from wimm.app import graphics_defaults

    assert graphics_defaults(environment={}) == {
        "GSK_RENDERER": "cairo",
        "GDK_DEBUG": "gl-disable,vulkan-disable",
    }
    # A user choice wins: nothing is overridden.
    assert graphics_defaults(environment={"GSK_RENDERER": "ngl", "GDK_DEBUG": "misc"}) == {}


def test_window_host_survives_a_window_that_cannot_open(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from wimm.app import WindowHost

    attempts: list[int] = []

    def failing() -> RecordingWindow:
        attempts.append(1)
        raise RuntimeError("Gtk couldn't be initialized")

    host = WindowHost(factory=failing)
    with caplog.at_level(level=logging.INFO):
        host.present(group_id="example")
        host.present(group_id=None)
    assert len(attempts) == 2  # retried on the next request, not cached as broken
    assert "Window requested for group example" in caplog.messages
    assert any(message.startswith("Cannot open the window") for message in caplog.messages)


def test_build_window_fails_fast_without_a_display() -> None:
    environment = {
        key: value for key, value in os.environ.items() if key not in ("DISPLAY", "WAYLAND_DISPLAY")
    }
    result = subprocess.run(
        args=[
            sys.executable,
            "-c",
            "import time; from types import SimpleNamespace; from wimm.app import _build_window\n"
            "started = time.monotonic()\n"
            "try:\n"
            "    _build_window(application=SimpleNamespace(_service=None))\n"
            "except RuntimeError as error:\n"
            "    print(f'{error}|{time.monotonic() - started < 5}')",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == SUCCESS, result.stderr
    assert result.stdout == "No graphical display available|True\n"


def test_start_tray_failure_is_logged_and_leaves_no_tray(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import wimm.tray.tray
    from wimm.app import _start_tray

    def broken(**_kwargs: object) -> None:
        raise RuntimeError("no tray")

    monkeypatch.setattr(target=wimm.tray.tray, name="Tray", value=broken)
    application = SimpleNamespace(_tray=None, _service=object(), _window_host=None)
    _start_tray(application=application, connection=object())
    assert application._tray is None
    assert any(message.startswith("Cannot show the tray icon") for message in caplog.messages)


def test_shutdown_closes_everything_even_when_one_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gi.repository import Gio

    from wimm.app import _shutdown

    closed: list[str] = []

    def failing_close() -> None:
        closed.append("tray")
        raise RuntimeError("bus gone")

    monkeypatch.setattr(
        target=Gio.Application, name="do_shutdown", value=lambda _app: closed.append("gio")
    )
    application = SimpleNamespace(
        _service=SimpleNamespace(stop=lambda: closed.append("service")),
        _tray=SimpleNamespace(close=failing_close),
        _inspector=SimpleNamespace(close=lambda: closed.append("inspector")),
        _signals=(),
    )
    _shutdown(application=application)
    assert closed == ["service", "tray", "inspector", "gio"]


def test_status_does_not_import_gtk() -> None:
    result = subprocess.run(
        args=[
            sys.executable,
            "-c",
            "import sys; from wimm.app import main; "
            'assert main(argv=["status", "--json"]) in (0, 3); '
            'assert "gi.repository.Gtk" not in sys.modules; '
            'assert "gi.repository.Adw" not in sys.modules',
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"},
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_normal_app_import_does_load_gtk() -> None:
    result = subprocess.run(
        args=[
            sys.executable,
            "-c",
            "import sys; import wimm.ui.window; "
            'assert "gi.repository.Gtk" in sys.modules; '
            'assert "gi.repository.Adw" in sys.modules',
        ],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
