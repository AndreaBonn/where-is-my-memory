import subprocess
from typing import Any

import psutil
import pytest

from wimm.redaction import REDACTED
from wimm.service.errors import ControlFailed
from wimm.service.fs_controls import OUTPUT_TAIL_CHARS, SubprocessRunner, list_process_identities


def make_runner(*, stdout: str, stderr: str = "", returncode: int = 0) -> SubprocessRunner:
    def fake_run(argv: list[str], **_kwargs: Any) -> "subprocess.CompletedProcess[str]":
        return subprocess.CompletedProcess(
            args=argv, returncode=returncode, stdout=stdout, stderr=stderr
        )

    return SubprocessRunner(run=fake_run)


def test_runner_output_hides_secrets_before_it_reaches_the_ui() -> None:
    runner = make_runner(stdout="start ok\n", stderr="failed --token=abc123 now\n", returncode=2)

    result = runner.run(argv=["tool"], timeout_s=1.0)

    assert result.returncode == 2
    assert "abc123" not in result.output
    assert REDACTED in result.output
    assert "start ok" in result.output


def test_runner_output_keeps_only_the_last_200_characters() -> None:
    runner = make_runner(stdout="A" * 150 + "B" * 250)

    result = runner.run(argv=["tool"], timeout_s=1.0)

    assert OUTPUT_TAIL_CHARS == 200
    assert result.output == "B" * 200


def test_runner_redacts_a_secret_even_when_it_falls_in_the_kept_tail() -> None:
    runner = make_runner(stdout="x" * 500 + " --password=hunter2")

    result = runner.run(argv=["tool"], timeout_s=1.0)

    assert "hunter2" not in result.output
    assert result.output.endswith(f"--password={REDACTED}")


def _runner_raising(error: OSError) -> SubprocessRunner:
    def failing(argv: list[str], **_kwargs: Any) -> "subprocess.CompletedProcess[str]":
        raise error

    return SubprocessRunner(run=failing)


def test_runner_os_error_other_than_a_missing_tool_is_a_control_failure_naming_the_tool() -> None:
    runner = _runner_raising(PermissionError(13, "Permission denied"))

    with pytest.raises(ControlFailed, match=r"Cannot run tool: .*Permission denied"):
        runner.run(argv=["tool"], timeout_s=1.0)


def test_runner_missing_tool_is_reported_as_not_found_not_as_a_generic_failure() -> None:
    runner = _runner_raising(FileNotFoundError(2, "No such file"))

    with pytest.raises(ControlFailed, match="tool was not found on PATH") as raised:
        runner.run(argv=["tool"], timeout_s=1.0)

    assert "Cannot run" not in raised.value.message


class _ListedProcess:
    def __init__(self, *, info: dict[str, Any]) -> None:
        self.info = info


def test_process_identities_use_empty_values_for_what_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed = [
        _ListedProcess(info={"name": None, "cmdline": None}),
        _ListedProcess(info={"name": "python3", "cmdline": ["python3", "app.py"]}),
        _ListedProcess(info={"name": "kworker", "cmdline": []}),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: iter(listed))

    assert list_process_identities() == [
        ("", []),
        ("python3", ["python3", "app.py"]),
        ("kworker", []),
    ]
