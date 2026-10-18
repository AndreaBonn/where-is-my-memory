import subprocess
from typing import Any

from wimm.redaction import REDACTED
from wimm.service.fs_controls import OUTPUT_TAIL_CHARS, SubprocessRunner


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
