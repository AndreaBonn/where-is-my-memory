"""F12: a plain `uv run pytest` never reaches the user's desktop session."""

import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from gi.repository import Gio, GLib

from tests.private_session import OUTER_KEY, SESSION_KEY, PrivateSession

FLAGS = (
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
)
DEATH_TIMEOUT_S = 5.0
ROOT = Path(__file__).resolve().parents[1]


def bus_id(connection: Gio.DBusConnection) -> str:
    reply = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "GetId",
        None,
        GLib.VariantType("(s)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    return str(reply.unpack()[0])


def test_gio_session_bus_is_the_private_one(pytestconfig: pytest.Config) -> None:
    session: PrivateSession = pytestconfig.stash[SESSION_KEY]
    private = Gio.DBusConnection.new_for_address_sync(session.bus_address, FLAGS, None, None)

    session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    assert bus_id(session_bus) == bus_id(private)
    outer = pytestconfig.stash[OUTER_KEY].get("DBUS_SESSION_BUS_ADDRESS")
    if outer:  # Paired positive: the desktop bus is reachable and is another bus.
        desktop = Gio.DBusConnection.new_for_address_sync(outer, FLAGS, None, None)
        assert bus_id(desktop) != bus_id(private)


def test_killing_pytest_leaves_no_display_or_bus_behind(tmp_path: Path) -> None:
    # A Stop hook timeout kills pytest outright: no cleanup runs, the kernel must reap both.
    pids = tmp_path / "pids"
    (tmp_path / "test_hold.py").write_text(
        "import os, time\n"
        "from tests.private_session import SESSION_KEY\n\n"
        "def test_hold(pytestconfig):\n"
        "    s = pytestconfig.stash[SESSION_KEY]\n"
        "    fields = (s.xvfb.pid, s.bus.pid, s.runtime_dir)\n"
        f"    open({str(pids)!r}, 'w').write(' '.join(map(str, fields)))\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    child = subprocess.Popen(  # noqa: S603 - fixed argv
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests.conftest",
            str(tmp_path),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while not pids.exists() or not pids.read_text():
            assert time.monotonic() < deadline, "the child test never started"
            time.sleep(0.05)
        *numbers, runtime_dir = pids.read_text().split()
        started = [int(pid) for pid in numbers]
        assert all(alive(pid=pid) for pid in started)
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait()
    # Killed outright, the child could not remove its runtime dir; the test does.
    shutil.rmtree(runtime_dir, ignore_errors=True)

    deadline = time.monotonic() + DEATH_TIMEOUT_S
    while any(alive(pid=pid) for pid in started) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not any(alive(pid=pid) for pid in started)


def alive(*, pid: int) -> bool:
    """True while the process exists and is not a zombie waiting for its parent."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


def test_the_private_bus_activates_services_on_the_private_display(
    pytestconfig: pytest.Config,
) -> None:
    # The bus starts services such as the AT-SPI launcher with its own environment, so that
    # environment must name the private display and no part of the desktop session.
    session: PrivateSession = pytestconfig.stash[SESSION_KEY]
    outer = pytestconfig.stash[OUTER_KEY]

    raw = Path(f"/proc/{session.bus.pid}/environ").read_bytes().split(b"\0")
    environ = dict(item.decode().split("=", 1) for item in raw if b"=" in item)

    assert environ["DISPLAY"] == session.display
    assert "WAYLAND_DISPLAY" not in environ
    assert "DBUS_SESSION_BUS_ADDRESS" not in environ
    assert environ["XDG_RUNTIME_DIR"] == str(session.runtime_dir)
    assert environ["XDG_RUNTIME_DIR"] != outer.get("XDG_RUNTIME_DIR")
    # Activated services (dconf, gvfs) write under HOME and XDG dirs: those are private too.
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        assert Path(environ[name]).is_relative_to(session.runtime_dir), name
