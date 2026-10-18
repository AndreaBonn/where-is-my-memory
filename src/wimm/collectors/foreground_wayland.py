import logging
import os
from collections.abc import Callable
from typing import Any, Protocol

from wimm.collectors.foreground import (
    DISABLED_STATE,
    UNAVAILABLE_STATE,
    ForegroundState,
    ForegroundStatus,
)

LOGGER = logging.getLogger(__name__)
WAYLAND_SESSION = "wayland"
X11_SESSION = "x11"
FOCUS_BUS_NAME = "io.github.wimm.Focus"
FOCUS_OBJECT_PATH = "/io/github/wimm/Focus"
FOCUS_INTERFACE = "io.github.wimm.Focus1"
FOCUS_PROPERTY = "FocusedPid"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
DAEMON_NAME = "org.freedesktop.DBus"
DAEMON_PATH = "/org/freedesktop/DBus"
GNOME_SHELL_EXE = "/usr/bin/gnome-shell"
CALL_TIMEOUT_MS = 200
type ProxyFactory = Callable[..., Any]
type Identity = Callable[[int], tuple[str, int]]


class FocusBusError(Exception):
    """The session bus could not answer: no name owner, timeout, no bus or a malformed reply."""


class FocusBus(Protocol):
    def owner_pid(self) -> int: ...

    def focused_pid(self) -> int: ...


def is_wayland_session(*, session_type: str | None, wayland_display: str | None) -> bool:
    """An explicit session type wins; without one, a Wayland display marks the session."""
    if session_type == WAYLAND_SESSION:
        return True
    if session_type == X11_SESSION:
        return False
    return bool(wayland_display)


def is_trusted_owner(*, pid: int, exe: str, uid: int, own_uid: int) -> bool:
    """The focus name is trusted only when held by the user's own GNOME Shell."""
    return pid > 0 and exe == GNOME_SHELL_EXE and uid == own_uid


def read_process_identity(pid: int) -> tuple[str, int]:
    """Return the executable path and owner uid of a process; raises OSError when unreadable."""
    return os.readlink(f"/proc/{pid}/exe"), os.stat(f"/proc/{pid}").st_uid


def open_proxy(*, name: str, path: str, interface: str) -> Any:
    from gi.repository import Gio

    flags = (
        Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES
        | Gio.DBusProxyFlags.DO_NOT_CONNECT_SIGNALS
        | Gio.DBusProxyFlags.DO_NOT_AUTO_START
    )
    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, flags, None, name, path, interface, None
    )


class GioFocusBus:
    """Synchronous Gio proxies with a short timeout; every Gio failure is a FocusBusError."""

    def __init__(self, *, proxy_factory: ProxyFactory = open_proxy) -> None:
        self._factory = proxy_factory
        self._daemon: Any = None
        self._focus: Any = None

    def owner_pid(self) -> int:
        """Ask the bus daemon which process holds the focus name."""
        from gi.repository import GLib

        try:
            if self._daemon is None:
                self._daemon = self._factory(
                    name=DAEMON_NAME, path=DAEMON_PATH, interface=DAEMON_NAME
                )
            params = GLib.Variant("(s)", (FOCUS_BUS_NAME,))
            return _as_pid(
                self._call(proxy=self._daemon, method="GetConnectionUnixProcessID", params=params)
            )
        except GLib.Error as error:
            self._daemon = None
            raise FocusBusError(str(error)) from error

    def focused_pid(self) -> int:
        """Read FocusedPid through org.freedesktop.DBus.Properties."""
        from gi.repository import GLib

        try:
            if self._focus is None:
                self._focus = self._factory(
                    name=FOCUS_BUS_NAME, path=FOCUS_OBJECT_PATH, interface=PROPERTIES_INTERFACE
                )
            params = GLib.Variant("(ss)", (FOCUS_INTERFACE, FOCUS_PROPERTY))
            return _as_pid(self._call(proxy=self._focus, method="Get", params=params))
        except GLib.Error as error:
            self._focus = None
            raise FocusBusError(str(error)) from error

    @staticmethod
    def _call(*, proxy: Any, method: str, params: Any) -> Any:
        from gi.repository import Gio

        reply = proxy.call_sync(
            method, params, Gio.DBusCallFlags.NO_AUTO_START, CALL_TIMEOUT_MS, None
        )
        return reply.unpack()[0]


def _as_pid(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FocusBusError(f"expected an integer pid, got {value!r}")
    return value


class WaylandForegroundReader:
    """Reads the foreground PID published by the GNOME Shell extension; never raises.

    The name owner is checked on every read through the bus daemon (one cheap call), but the
    /proc lookup runs only when the owner pid differs from the last trusted one: a restarted
    or replaced owner gets a new pid and is verified again.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        bus: FocusBus | None = None,
        own_uid: int | None = None,
        identity: Identity = read_process_identity,
    ) -> None:
        self._enabled = enabled
        self._bus: FocusBus = bus if bus is not None else GioFocusBus()
        self._own_uid = os.getuid() if own_uid is None else own_uid
        self._identity = identity
        self._trusted_pid: int | None = None

    def read(self) -> ForegroundState:
        if not self._enabled:
            return DISABLED_STATE
        try:
            return self._read()
        except (FocusBusError, OSError):
            LOGGER.debug("wayland foreground lookup failed", exc_info=True)
            return UNAVAILABLE_STATE

    def _read(self) -> ForegroundState:
        if not self._owner_is_trusted(pid=self._bus.owner_pid()):
            return UNAVAILABLE_STATE
        pid = self._bus.focused_pid()
        if pid <= 0:
            return UNAVAILABLE_STATE
        return ForegroundState(status=ForegroundStatus.ACTIVE, pid=pid)

    def _owner_is_trusted(self, *, pid: int) -> bool:
        if pid == self._trusted_pid:
            return True
        self._trusted_pid = None
        exe, uid = self._identity(pid)
        if not is_trusted_owner(pid=pid, exe=exe, uid=uid, own_uid=self._own_uid):
            return False
        self._trusted_pid = pid
        return True
