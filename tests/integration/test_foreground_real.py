import os
import re
import shutil
import subprocess

import pytest

from wimm.collectors.foreground import ForegroundReader, ForegroundState, ForegroundStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") != "x11",
        reason="needs a live X11 session",
    ),
]
STABLE_ATTEMPTS = 5
ACTIVE_ID = re.compile(r"window id # (0x[0-9a-fA-F]+)")
XPROP = shutil.which("xprop") or "xprop"
OWNER_PID = re.compile(r"_NET_WM_PID\(CARDINAL\) = (\d+)")


def xprop(*args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, window ids read from the X server
        [XPROP, *args], capture_output=True, text=True, timeout=5, check=False
    )
    return result.stdout if result.returncode == 0 else ""


def foreground_seen_by_xprop() -> ForegroundState:
    """What the session says right now, asked of xprop directly and parsed by this test."""
    root = ACTIVE_ID.search(xprop("-root", "_NET_ACTIVE_WINDOW"))
    if root is None or int(root.group(1), 16) == 0:
        return ForegroundState(status=ForegroundStatus.UNAVAILABLE)
    owner = OWNER_PID.search(xprop("-id", root.group(1), "_NET_WM_PID"))
    if owner is None or int(owner.group(1)) == 0:
        return ForegroundState(status=ForegroundStatus.UNAVAILABLE)
    return ForegroundState(status=ForegroundStatus.ACTIVE, pid=int(owner.group(1)))


@pytest.mark.skipif(shutil.which("xprop") is None, reason="needs xprop")
def test_real_x11_read_reports_the_window_the_session_has_in_front() -> None:
    reader = ForegroundReader.from_environment(enabled=True)
    # The focus can move during a read: only a read framed by two equal views is judged.
    for _ in range(STABLE_ATTEMPTS):
        before = foreground_seen_by_xprop()
        state = reader.read()
        if foreground_seen_by_xprop() == before:
            break
    else:
        pytest.skip("the focus kept moving during every read")
    assert state == before
    assert (state.pid is not None) == (state.status is ForegroundStatus.ACTIVE)
