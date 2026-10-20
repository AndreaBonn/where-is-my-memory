"""T-6.37c: the real `ollama list` runner, with an injected `subprocess.run` (no real ollama)."""

import subprocess
from typing import Any

import pytest

from wimm.collectors.ollama_command import CommandOutput, OllamaCommandError, run_command


class RecordingRun:
    def __init__(self, *, result: Any = None, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.args: list[Any] = []
        self.kwargs: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.args, self.kwargs = list(args), kwargs
        if self.error is not None:
            raise self.error
        return self.result


def test_runs_an_argv_list_without_a_shell_and_returns_the_full_output() -> None:
    long_output = "x" * 5000
    run = RecordingRun(
        result=subprocess.CompletedProcess(args=[], returncode=0, stdout=long_output, stderr="w")
    )
    out = run_command(argv=["/bin/ollama", "list"], timeout_s=10, env={"PATH": "/bin"}, run=run)
    assert out == CommandOutput(returncode=0, stdout=long_output, stderr="w")
    assert run.args == [["/bin/ollama", "list"]]
    assert run.kwargs["env"] == {"PATH": "/bin"}
    assert run.kwargs["timeout"] == 10
    assert run.kwargs["stdin"] == subprocess.DEVNULL
    assert not run.kwargs.get("shell")


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(cmd="ollama", timeout=10),
        FileNotFoundError("gone"),
        PermissionError("denied"),
    ],
)
def test_a_command_that_cannot_run_or_times_out_raises_the_collector_error(
    error: BaseException,
) -> None:
    with pytest.raises(OllamaCommandError):
        run_command(
            argv=["/bin/ollama", "list"], timeout_s=10, env={}, run=RecordingRun(error=error)
        )
