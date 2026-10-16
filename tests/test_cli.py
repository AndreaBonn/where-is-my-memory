import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import ISOLATED_DIRECTORIES
from wimm import __version__
from wimm.app import main

SUCCESS = 0
SUBPROCESS_TIMEOUT_SECONDS = 30
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_main_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv=["--version"]) == SUCCESS
    captured = capsys.readouterr()
    assert captured.out == f"wimm {__version__}\n"
    assert captured.err == ""


def test_main_reads_process_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target=sys, name="argv", value=["wimm", "--version"])
    assert main() == SUCCESS


def test_cli_version_subprocess() -> None:
    result = subprocess.run(
        args=["/usr/bin/env", "uv", "run", "wimm", "--version"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert result.returncode == SUCCESS, result.stderr
    assert result.stdout == f"wimm {__version__}\n"
    assert result.stderr == ""


def test_version_does_not_import_gi_or_register_on_bus() -> None:
    result = subprocess.run(
        args=[
            sys.executable,
            "-c",
            "import sys; from wimm.app import main; "
            'assert "gi" not in sys.modules; '
            'assert main(argv=["--version"]) == 0; '
            'assert "gi" not in sys.modules',
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"},
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"wimm {__version__}\n"


def test_user_directories_are_isolated(tmp_path: Path) -> None:
    assert Path(os.path.expanduser("~")) == tmp_path / "home"
    for variable, directory in ISOLATED_DIRECTORIES.items():
        assert Path(os.environ[variable]) == tmp_path / directory
    assert os.environ["WIMM_TEST"] == "1"


def test_application_id_and_unknown_option_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    from wimm.app import create_application

    monkeypatch.setenv(name="WIMM_APP_ID", value="io.github.wimm.Test")
    application = create_application()
    assert application.get_application_id() == "io.github.wimm.Test"
    assert application.run(["wimm", "--unknown"]) != SUCCESS


def test_module_version_subprocess() -> None:
    result = subprocess.run(
        args=["/usr/bin/env", "uv", "run", "python", "-m", "wimm", "--version"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert result.returncode == SUCCESS, result.stderr
    assert result.stdout == f"wimm {__version__}\n"
    assert result.stderr == ""


def test_window_host_logs_placeholder_and_group(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from wimm.app import WindowHost

    host = WindowHost()
    with caplog.at_level(level=logging.INFO):
        host.present(group_id=None)
        host.present(group_id="example")
    assert caplog.messages == [
        "window not implemented yet",
        "Requested group example",
        "window not implemented yet",
    ]


def test_background_service_two_cycles_do_not_import_gtk_or_adw() -> None:
    result = subprocess.run(
        args=[
            sys.executable,
            "-c",
            "from gi.repository import Gio; "
            "from wimm.app import create_application; "
            "from tests.service.test_app_service import FakeSampler, spin_until; "
            "from wimm.service.app_service import AppService; "
            "from wimm.service.inspector_dbus import Inspector; from wimm.config import Config; "
            "import sys; "
            "app = create_application(); assert isinstance(app, Gio.Application); "
            "assert app.get_flags() == Gio.ApplicationFlags.HANDLES_COMMAND_LINE; "
            "sampler = FakeSampler(); sampler.proceed.set(); "
            "service = AppService(sampler=sampler, config=Config()); "
            "updates = []; service.connect('snapshot-updated', lambda *_: updates.append(True)); "
            "service.start(); spin_until(predicate=lambda: len(updates) == 1); "
            "service.request_cycle(); spin_until(predicate=lambda: len(updates) == 2); "
            "service.stop(); assert sampler.calls == 2; "
            "assert 'gi.repository.Gtk' not in sys.modules; "
            "assert 'gi.repository.Adw' not in sys.modules; print('cycles=2 Gtk=False Adw=False')",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == SUCCESS, result.stderr
    assert result.stdout == "cycles=2 Gtk=False Adw=False\n"


@pytest.mark.parametrize(
    "options,expected",
    [({}, [None]), ({"group": "example"}, ["example"]), ({"background": True}, [])],
)
def test_command_line_routes_window_requests(
    options: dict[str, str | bool], expected: list[str | None]
) -> None:
    from gi.repository import GLib

    from wimm.app import _activate, _command_line

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
