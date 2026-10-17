import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

LOGGER = logging.getLogger(__name__)
XPROP_TIMEOUT_S = 1.0
XPROP_BINARY = "xprop"
X11_SESSION = "x11"
ACTIVE_WINDOW_PROPERTY = "_NET_ACTIVE_WINDOW"
WINDOW_PID_PROPERTY = "_NET_WM_PID"
ACTIVE_WINDOW_RE = re.compile(
    r"^_NET_ACTIVE_WINDOW\(WINDOW\): window id # (0x[0-9a-fA-F]+)\s*$", re.M
)
WINDOW_PID_RE = re.compile(r"^_NET_WM_PID\(CARDINAL\) = (\d+)\s*$", re.M)
type Runner = Callable[..., Any]
type Which = Callable[[str], str | None]


class ForegroundStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ForegroundState:
    status: ForegroundStatus
    pid: int | None = None


DISABLED_STATE = ForegroundState(status=ForegroundStatus.DISABLED)
UNAVAILABLE_STATE = ForegroundState(status=ForegroundStatus.UNAVAILABLE)


def parse_active_window_id(output: str) -> int | None:
    """Return the active window id from ``xprop -root`` output, or None."""
    match = ACTIVE_WINDOW_RE.search(output)
    window_id = int(match.group(1), 16) if match else 0
    return window_id or None


def parse_window_pid(output: str) -> int | None:
    """Return the owner PID from ``xprop -id`` output, or None."""
    match = WINDOW_PID_RE.search(output)
    return (int(match.group(1)) or None) if match else None


class ForegroundReader:
    """Reads the PID of the foreground X11 window; never raises."""

    def __init__(
        self,
        *,
        enabled: bool,
        session_type: str | None,
        which: Which = shutil.which,
        runner: Runner = subprocess.run,
    ) -> None:
        self._runner = runner
        self._xprop: str | None = None
        self._active = enabled and session_type == X11_SESSION
        if self._active:
            self._xprop = which(XPROP_BINARY)

    @classmethod
    def from_environment(cls, *, enabled: bool) -> "ForegroundReader":
        return cls(enabled=enabled, session_type=os.environ.get("XDG_SESSION_TYPE"))

    def read(self) -> ForegroundState:
        if self._xprop is None:
            return DISABLED_STATE
        try:
            return self._read(xprop=self._xprop)
        except (OSError, subprocess.SubprocessError, ValueError):
            LOGGER.debug("foreground lookup failed", exc_info=True)
            return UNAVAILABLE_STATE

    def _read(self, *, xprop: str) -> ForegroundState:
        root = self._run([xprop, "-root", ACTIVE_WINDOW_PROPERTY])
        window_id = parse_active_window_id(root) if root is not None else None
        if window_id is None:
            return UNAVAILABLE_STATE
        owner = self._run([xprop, "-id", hex(window_id), WINDOW_PID_PROPERTY])
        pid = parse_window_pid(owner) if owner is not None else None
        if pid is None:
            return UNAVAILABLE_STATE
        return ForegroundState(status=ForegroundStatus.ACTIVE, pid=pid)

    def _run(self, args: Sequence[str]) -> str | None:
        result = self._runner(
            list(args),
            capture_output=True,
            text=True,
            timeout=XPROP_TIMEOUT_S,
            check=False,
        )
        if result.returncode != 0 or not isinstance(result.stdout, str):
            return None
        return result.stdout
