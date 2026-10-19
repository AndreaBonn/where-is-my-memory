import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.cli_helpers import PROJECT_ROOT, SUBPROCESS_TIMEOUT_SECONDS, SUCCESS
from tests.conftest import ISOLATED_DIRECTORIES
from wimm import __version__
from wimm.app import main


def test_main_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv=["--version"]) == SUCCESS
    captured = capsys.readouterr()
    assert captured.out == f"wimm {__version__}\n"
    assert captured.err == ""


def test_main_version_is_honoured_anywhere_in_the_arguments(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_application() -> None:
        # Fail loudly instead of starting a real application if the flag is ignored.
        pytest.fail("the application must not start")

    monkeypatch.setattr("wimm.app.create_application", no_application)
    assert main(argv=["--background", "--version"]) == SUCCESS
    assert capsys.readouterr().out == f"wimm {__version__}\n"


def test_main_status_keeps_its_own_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def recording_status(*, arguments: list[str]) -> int:
        seen.append(arguments)
        return SUCCESS

    monkeypatch.setattr("wimm.cli_status.run_status", recording_status)
    assert main(argv=["status", "--version"]) == SUCCESS
    assert seen == [["--version"]]


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


def test_program_name_is_the_application_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # GTK names the X11 WM_CLASS after it: the dock matches it to StartupWMClass for the icon.
    from gi.repository import GLib

    from wimm.app import create_application

    monkeypatch.setenv(name="WIMM_APP_ID", value="io.github.wimm.Test")
    create_application()
    assert GLib.get_prgname() == "io.github.wimm.Test"


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


class RecordingWindow:
    def __init__(self) -> None:
        self.shown: list[str | None] = []
        self.tray_missing: list[bool] = []

    def show_group(self, group_id: str | None) -> None:
        self.shown.append(group_id)

    def set_tray_missing(self, missing: bool) -> None:
        self.tray_missing.append(missing)

    def get_visible(self) -> bool:
        return True

    def save_size(self) -> None:
        pass

    def destroy(self) -> None:
        pass


def test_window_host_builds_the_window_once_and_reuses_it() -> None:
    from wimm.app import WindowHost

    built: list[RecordingWindow] = []

    def factory() -> RecordingWindow:
        built.append(RecordingWindow())
        return built[-1]

    host = WindowHost(factory=factory)
    assert built == []  # nothing (and no GTK) until the first request
    host.present(group_id=None)
    host.present(group_id="g_3f9a1c")
    assert len(built) == 1
    assert built[0].shown == [None, "g_3f9a1c"]


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
