import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ISOLATED_DIRECTORIES
from wimm import __version__
from wimm.app import main

SUCCESS = 0
NOT_IMPLEMENTED = 2
SUBPROCESS_TIMEOUT_SECONDS = 30
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_main_version_exits_successfully_without_gi(capsys: pytest.CaptureFixture[str]) -> None:
    assert "gi" not in sys.modules
    assert main(argv=["--version"]) == SUCCESS
    captured = capsys.readouterr()
    assert captured.out == f"wimm {__version__}\n"
    assert captured.err == ""
    assert "gi" not in sys.modules


@pytest.mark.parametrize("argv", [[], ["--unknown"], ["--version", "--unknown"], [""]])
def test_main_other_arguments_report_unimplemented_gui(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv=argv) == NOT_IMPLEMENTED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "GUI not implemented yet\n"


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


def test_user_directories_are_isolated(tmp_path: Path) -> None:
    assert Path(os.path.expanduser("~")) == tmp_path / "home"
    for variable, directory in ISOLATED_DIRECTORIES.items():
        assert Path(os.environ[variable]) == tmp_path / directory
    assert os.environ["WIMM_TEST"] == "1"
