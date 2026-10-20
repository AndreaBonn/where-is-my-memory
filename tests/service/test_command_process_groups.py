import ctypes
import os
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import psutil
import pytest

from wimm.collectors.ollama_command import OllamaCommandError, run_command
from wimm.service.errors import ControlFailed
from wimm.service.fs_controls import SubprocessRunner

TIMEOUT_S = 0.3
NORMAL_TIMEOUT_S = 5.0
EXIT_WAIT_S = 2.0
POLL_S = 0.01
PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37
pytestmark = pytest.mark.usefixtures("adopt_grandchildren")
CHILD_CODE = """import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(60)
"""


@pytest.fixture
def adopt_grandchildren() -> Iterator[None]:
    # Reap orphaned test children even when the container's PID 1 does not reap them.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    try:
        yield
    finally:
        assert libc.prctl(PR_SET_CHILD_SUBREAPER, previous.value, 0, 0, 0) == 0


def invoke(*, runner: str, argv: list[str], timeout_s: float) -> str:
    if runner == "service":
        result = SubprocessRunner().run(argv=argv, timeout_s=timeout_s)
        assert result.returncode == 0
        return result.output
    output = run_command(argv=argv, timeout_s=timeout_s, env=dict(os.environ))
    assert output.returncode == 0
    return output.stdout.strip()


def running(*, pid: int) -> bool:
    with suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    return psutil.pid_exists(pid=pid)


@pytest.mark.parametrize("runner", ["service", "collector"])
def test_timeout_kills_grandchildren_and_normal_commands_return_output(
    runner: str, tmp_path: Path
) -> None:
    script, pid_file = tmp_path / "parent.py", tmp_path / "grandchild.pid"
    script.write_text(data=CHILD_CODE)
    error = ControlFailed if runner == "service" else OllamaCommandError
    try:
        with pytest.raises(error, match="did not finish within"):
            invoke(
                runner=runner,
                argv=[sys.executable, str(script), str(pid_file)],
                timeout_s=TIMEOUT_S,
            )
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + EXIT_WAIT_S
        while running(pid=pid) and time.monotonic() < deadline:
            time.sleep(POLL_S)
        assert not running(pid=pid), f"grandchild {pid} survived the timeout"
        argv = [sys.executable, "-c", "print('normal output')"]
        assert invoke(runner=runner, argv=argv, timeout_s=NORMAL_TIMEOUT_S) == "normal output"
    finally:
        if pid_file.exists() and running(pid=int(pid_file.read_text())):
            pid = int(pid_file.read_text())
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)


ESCAPED_HOLD_S = 3
ESCAPE_BUDGET_S = 2.0


def test_a_descendant_outside_the_group_does_not_hold_the_timeout(tmp_path: Path) -> None:
    # V1: a child that left the group with setsid keeps the output pipes open; the runner must
    # still give up shortly after its own timeout instead of waiting for that child.
    script = f"setsid sleep {ESCAPED_HOLD_S} & sleep 30"
    started = time.monotonic()
    with pytest.raises(OllamaCommandError, match="did not finish"):
        run_command(
            argv=["/bin/sh", "-c", script], timeout_s=TIMEOUT_S, env={"PATH": "/usr/bin:/bin"}
        )
    assert time.monotonic() - started < ESCAPE_BUDGET_S
