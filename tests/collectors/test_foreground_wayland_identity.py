import os
import subprocess
import sys

import pytest
from gi.repository import GLib

from tests.collectors.foreground_wayland_helpers import (
    FOCUSED_PID,
    SHELL_PID,
    FakeProxy,
    glib_error,
    properties_reply,
)
from wimm.collectors.foreground_wayland import FocusBusError, GioFocusBus, read_process_identity


def test_process_identity_of_this_process_is_its_executable_and_owner() -> None:
    exe, uid = read_process_identity(pid=os.getpid())

    assert exe == os.path.realpath(sys.executable)
    assert uid == os.getuid()


def test_process_identity_of_a_process_that_is_gone_raises_oserror() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()

    with pytest.raises(OSError):
        read_process_identity(pid=child.pid)


def test_gio_bus_reuses_each_proxy_while_calls_succeed() -> None:
    created: list[str] = []
    proxies = {
        "org.freedesktop.DBus": FakeProxy(reply=GLib.Variant("(u)", (SHELL_PID,))),
        "org.freedesktop.DBus.Properties": FakeProxy(reply=properties_reply(FOCUSED_PID)),
    }

    def factory(*, name: str, path: str, interface: str) -> FakeProxy:
        created.append(interface)
        return proxies[interface]

    bus = GioFocusBus(proxy_factory=factory)

    assert [bus.owner_pid(), bus.owner_pid()] == [SHELL_PID, SHELL_PID]
    assert [bus.focused_pid(), bus.focused_pid()] == [FOCUSED_PID, FOCUSED_PID]
    assert sorted(created) == ["org.freedesktop.DBus", "org.freedesktop.DBus.Properties"]


def test_gio_bus_opens_a_new_proxy_after_a_call_failed() -> None:
    broken = FakeProxy(error=glib_error("connection closed"))
    healthy_daemon = FakeProxy(reply=GLib.Variant("(u)", (SHELL_PID,)))
    healthy_focus = FakeProxy(reply=properties_reply(FOCUSED_PID))
    queues: dict[str, list[FakeProxy]] = {
        "org.freedesktop.DBus": [broken, healthy_daemon],
        "org.freedesktop.DBus.Properties": [broken, healthy_focus],
    }

    def factory(*, name: str, path: str, interface: str) -> FakeProxy:
        return queues[interface].pop(0)

    bus = GioFocusBus(proxy_factory=factory)
    with pytest.raises(FocusBusError):
        bus.owner_pid()
    with pytest.raises(FocusBusError):
        bus.focused_pid()

    assert bus.owner_pid() == SHELL_PID
    assert bus.focused_pid() == FOCUSED_PID
