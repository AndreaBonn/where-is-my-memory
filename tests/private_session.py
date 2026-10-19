"""A private X display and session bus for the whole test run (F12).

The Stop hook runs a plain `uv run pytest`, so tests must never reach the user's desktop:
GTK windows, the clipboard and the application registration on the session bus all go
here instead. Started in pytest_configure, before any test touches GTK or Gio's bus.
"""

import ctypes
import os
import select
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

XVFB = "Xvfb"
DBUS_DAEMON = "dbus-daemon"
SCREEN = "1280x1024x24"
START_TIMEOUT_S = 10
PR_SET_PDEATHSIG = 1
DESKTOP_VARIABLES = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "GDK_BACKEND",
    "XDG_RUNTIME_DIR",
)
# Where services the bus activates write (dconf, gvfs): kept under the private runtime dir.
BUS_HOME_DIRS = {
    "HOME": "home",
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_CACHE_HOME": "cache",
    "XDG_STATE_HOME": "state",
}
# Never handed to the bus: services it activates would reach the desktop session.
BUS_EXCLUDED = ("WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")
SESSION_KEY = pytest.StashKey["PrivateSession"]()
OUTER_KEY = pytest.StashKey[dict[str, str | None]]()


@dataclass(frozen=True, slots=True)
class PrivateSession:
    display: str
    bus_address: str
    xvfb: subprocess.Popen[bytes]
    bus: subprocess.Popen[bytes]
    runtime_dir: Path


def _die_with_parent() -> None:
    """Runs in the child: the kernel sends SIGTERM when pytest dies, even by SIGKILL."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def _executable(*, name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise pytest.UsageError(f"{name} is missing: the tests need a private display and bus")
    return path


def _first_line(*, fd: int, process: subprocess.Popen[bytes], name: str) -> str:
    """The line the server writes once it is ready; it is killed if none comes in time."""
    deadline = time.monotonic() + START_TIMEOUT_S
    data = b""
    while b"\n" not in data:
        ready, _, _ = select.select([fd], [], [], max(deadline - time.monotonic(), 0))
        chunk = os.read(fd, 4096) if ready else b""
        if not chunk:
            _stop(process=process)
            cause = "exited" if ready else f"was not ready within {START_TIMEOUT_S} s"
            raise pytest.UsageError(f"{name} {cause}: the tests need a private display and bus")
        data += chunk
    return data.split(b"\n", 1)[0].decode().strip()


def _start_display() -> tuple[subprocess.Popen[bytes], str]:
    """Xvfb on a free display number, which it writes to the pipe once it accepts clients."""
    read_end, write_end = os.pipe()
    try:
        argv = [_executable(name=XVFB), "-displayfd", str(write_end), "-nolisten", "tcp"]
        xvfb = subprocess.Popen(  # noqa: S603 - fixed argv
            [*argv, "-screen", "0", SCREEN],
            pass_fds=(write_end,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=_die_with_parent,
        )
        os.close(write_end)
        write_end = -1
        return xvfb, ":" + _first_line(fd=read_end, process=xvfb, name=XVFB)
    finally:
        os.close(read_end)
        if write_end >= 0:
            os.close(write_end)


def _start_bus(*, display: str, runtime_dir: Path) -> tuple[subprocess.Popen[bytes], str]:
    """A session dbus-daemon kept as our child, so it dies with the run.

    Services it activates (the AT-SPI launcher) inherit its environment: the private display
    and a private runtime dir, whose sockets cannot clash with the desktop's.
    """
    env = {name: value for name, value in os.environ.items() if name not in BUS_EXCLUDED}
    env.update(DISPLAY=display, GDK_BACKEND="x11", XDG_RUNTIME_DIR=str(runtime_dir))
    env.update({name: str(runtime_dir / sub) for name, sub in BUS_HOME_DIRS.items()})
    bus = subprocess.Popen(  # noqa: S603 - fixed argv
        [_executable(name=DBUS_DAEMON), "--session", "--nofork", "--print-address=1"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        preexec_fn=_die_with_parent,
    )
    assert bus.stdout is not None
    try:
        return bus, _first_line(fd=bus.stdout.fileno(), process=bus, name=DBUS_DAEMON)
    except BaseException:
        bus.stdout.close()
        raise


def start_private_session() -> tuple[PrivateSession, dict[str, str | None]]:
    """Start display and bus, point this process and its children at them."""
    outer = {name: os.environ.get(name) for name in DESKTOP_VARIABLES}
    xvfb, display = _start_display()
    runtime_dir = Path(tempfile.mkdtemp(prefix="wimm-test-runtime-"))
    try:
        bus, address = _start_bus(display=display, runtime_dir=runtime_dir)
    except BaseException:
        _stop(process=xvfb)
        shutil.rmtree(runtime_dir, ignore_errors=True)
        raise
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.update(DISPLAY=display, GDK_BACKEND="x11", DBUS_SESSION_BUS_ADDRESS=address)
    session = PrivateSession(
        display=display, bus_address=address, xvfb=xvfb, bus=bus, runtime_dir=runtime_dir
    )
    return session, outer


def _stop(*, process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=START_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def stop_private_session(*, session: PrivateSession) -> None:
    for process in (session.bus, session.xvfb):
        _stop(process=process)
    if session.bus.stdout is not None:
        session.bus.stdout.close()
    shutil.rmtree(session.runtime_dir, ignore_errors=True)
