import os
import stat
import time
from pathlib import Path

import pytest

from wimm.collectors.gpu import run_nvidia_smi

WAIT_LIMIT_S = 10.0
POLL_S = 0.02
TIMEOUT_S = 1.0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _read_pid(pid_file: Path) -> int:
    deadline = time.monotonic() + WAIT_LIMIT_S
    while time.monotonic() < deadline:
        text = pid_file.read_text().strip() if pid_file.exists() else ""
        if text.isdecimal():
            return int(text)
        time.sleep(POLL_S)
    raise AssertionError("the fake nvidia-smi never recorded its pid")


def test_a_hung_nvidia_smi_is_killed_when_the_timeout_expires(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    script = tmp_path / "smi"
    # The shell becomes `sleep` via exec, so the recorded pid is the process to be killed.
    script.write_text(f'#!/bin/sh\necho $$ > "{pid_file}"\nexec sleep 60\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    with pytest.raises(TimeoutError):
        run_nvidia_smi([str(script)], timeout_s=TIMEOUT_S)

    pid = _read_pid(pid_file)
    deadline = time.monotonic() + WAIT_LIMIT_S
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(POLL_S)
    assert not _alive(pid)
