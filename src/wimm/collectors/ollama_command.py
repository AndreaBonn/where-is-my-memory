"""Run `ollama list` for the scan: argument list, no shell, no stdin, the whole output kept."""

import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

NEUTRAL_CWD = "/"
# After the group is killed, how long to wait for the pipes: a descendant that left the group
# (setsid) may keep them open, and the caller's timeout must not stretch to its lifetime.
REAP_TIMEOUT_S = 0.5
_Run = Callable[..., "subprocess.CompletedProcess[str]"]


def _kill_group(*, child: subprocess.Popen[str]) -> None:
    """SIGKILL the child's whole group; the child alone if the group cannot be signalled."""
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        return  # the group exited between the timeout and the signal
    except PermissionError:
        child.kill()


def run_process_group(
    argv: list[str],
    *,
    timeout: float,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    **options: Any,
) -> subprocess.CompletedProcess[str]:
    """Capture output and reap the child after killing its whole group on timeout."""
    options.pop("capture_output", None)
    options.pop("check", None)
    with popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, **options
    ) as child:
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(child=child)
            # Leaving the `with` closes the pipes and reaps the child, which is now dead.
            with suppress(subprocess.TimeoutExpired):
                child.communicate(timeout=REAP_TIMEOUT_S)
            raise
        return subprocess.CompletedProcess(
            args=argv, returncode=child.returncode, stdout=stdout, stderr=stderr
        )


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
    run: _Run = run_process_group,
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
