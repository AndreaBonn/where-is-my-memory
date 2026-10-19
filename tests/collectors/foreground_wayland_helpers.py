from collections.abc import Callable
from typing import Any

from gi.repository import GLib

from wimm.collectors.foreground_wayland import (
    GNOME_SHELL_EXE,
    WaylandForegroundReader,
)

OWN_UID = 1000
SHELL_PID = 4321
FOCUSED_PID = 9876


class FakeBus:
    def __init__(
        self, *, owner: int | BaseException = SHELL_PID, focused: int | BaseException = FOCUSED_PID
    ) -> None:
        self.owner = owner
        self.focused = focused
        self.focused_calls = 0

    def owner_pid(self) -> int:
        if isinstance(self.owner, BaseException):
            raise self.owner
        return self.owner

    def focused_pid(self) -> int:
        self.focused_calls += 1
        if isinstance(self.focused, BaseException):
            raise self.focused
        return self.focused


class FakeIdentity:
    def __init__(self, table: dict[int, tuple[str, int] | BaseException]) -> None:
        self.table = table
        self.calls: list[int] = []

    def __call__(self, pid: int) -> tuple[str, int]:
        self.calls.append(pid)
        result = self.table[pid]
        if isinstance(result, BaseException):
            raise result
        return result


SHELL = (GNOME_SHELL_EXE, OWN_UID)


def make_reader(
    bus: FakeBus, identity: FakeIdentity | None = None, *, enabled: bool = True
) -> WaylandForegroundReader:
    return WaylandForegroundReader(
        enabled=enabled,
        bus=bus,
        own_uid=OWN_UID,
        identity=identity or FakeIdentity({SHELL_PID: SHELL}),
    )


class FakeProxy:
    def __init__(self, *, reply: Any = None, error: BaseException | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[str, Any, int]] = []

    def call_sync(
        self, method: str, params: Any, flags: Any, timeout_ms: int, cancellable: Any
    ) -> Any:
        self.calls.append((method, params, timeout_ms))
        if self.error is not None:
            raise self.error
        return self.reply


def factory_for(proxies: dict[str, FakeProxy]) -> Callable[..., Any]:
    def factory(*, name: str, path: str, interface: str) -> FakeProxy:
        return proxies[interface]

    return factory


def glib_error(message: str) -> GLib.Error:
    error: GLib.Error = GLib.Error.new_literal(GLib.quark_from_string("test"), message, 0)
    return error


def properties_reply(value: Any) -> Any:
    return GLib.Variant("(v)", (GLib.Variant("u", value),))
