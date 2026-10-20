"""Run `ollama list` for the scan: argument list, no shell, no stdin, the whole output kept."""

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

NEUTRAL_CWD = "/"
_Run = Callable[..., "subprocess.CompletedProcess[str]"]


class OllamaCommandError(Exception):
    """The command could not start or did not finish in time."""


@dataclass(frozen=True, slots=True)
class CommandOutput:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def __call__(
        self, *, argv: Sequence[str], timeout_s: float, env: Mapping[str, str]
    ) -> CommandOutput:
        """Run `argv`; raise `OllamaCommandError` if it cannot start or times out."""
        ...


def run_command(
    *,
    argv: Sequence[str],
    timeout_s: float,
    env: Mapping[str, str],
    run: _Run = subprocess.run,
) -> CommandOutput:
    """The real runner. The listing is parsed, so the output is not truncated or redacted."""
    tool = argv[0]
    try:
        done = run(
            list(argv),
            stdin=subprocess.DEVNULL,
            cwd=NEUTRAL_CWD,
            env=dict(env),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise OllamaCommandError(f"{tool} did not finish within {timeout_s} s") from error
    except OSError as error:
        raise OllamaCommandError(f"Cannot run {tool}: {error}") from error
    return CommandOutput(returncode=done.returncode, stdout=done.stdout, stderr=done.stderr)
