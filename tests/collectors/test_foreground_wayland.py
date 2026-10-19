from typing import Any

import pytest
from gi.repository import GLib

from tests.collectors.foreground_wayland_helpers import (
    FOCUSED_PID,
    OWN_UID,
    SHELL,
    SHELL_PID,
    FakeBus,
    FakeIdentity,
    FakeProxy,
    factory_for,
    glib_error,
    make_reader,
    properties_reply,
)
from wimm.collectors.foreground import (
    DISABLED_STATE,
    UNAVAILABLE_STATE,
    ForegroundReader,
    ForegroundState,
    ForegroundStatus,
)
from wimm.collectors.foreground_wayland import (
    FOCUS_INTERFACE,
    GNOME_SHELL_EXE,
    FocusBusError,
    GioFocusBus,
    WaylandForegroundReader,
    is_trusted_owner,
    is_wayland_session,
    open_proxy,
)


@pytest.mark.parametrize(
    ("pid", "exe", "uid", "expected"),
    [
        (SHELL_PID, GNOME_SHELL_EXE, OWN_UID, True),
        (SHELL_PID, "/usr/bin/evil", OWN_UID, False),
        (SHELL_PID, GNOME_SHELL_EXE + " (deleted)", OWN_UID, False),
        (SHELL_PID, GNOME_SHELL_EXE, OWN_UID + 1, False),
        (0, GNOME_SHELL_EXE, OWN_UID, False),
        (-1, GNOME_SHELL_EXE, OWN_UID, False),
    ],
)
def test_is_trusted_owner(pid: int, exe: str, uid: int, expected: bool) -> None:
    assert is_trusted_owner(pid=pid, exe=exe, uid=uid, own_uid=OWN_UID) is expected


@pytest.mark.parametrize(
    ("session_type", "wayland_display", "expected"),
    [
        ("wayland", None, True),
        ("wayland", "wayland-0", True),
        (None, "wayland-0", True),
        ("tty", "wayland-0", True),
        ("x11", "wayland-0", False),
        ("x11", None, False),
        (None, None, False),
        (None, "", False),
    ],
)
def test_is_wayland_session(
    session_type: str | None, wayland_display: str | None, expected: bool
) -> None:
    assert (
        is_wayland_session(session_type=session_type, wayland_display=wayland_display) is expected
    )


def test_trusted_owner_with_pid_returns_active_pid() -> None:
    state = make_reader(FakeBus()).read()
    assert state == ForegroundState(status=ForegroundStatus.ACTIVE, pid=FOCUSED_PID)


def test_missing_name_is_unavailable() -> None:
    bus = FakeBus(owner=FocusBusError("no owner"))
    assert make_reader(bus).read() == UNAVAILABLE_STATE
    assert bus.focused_calls == 0


@pytest.mark.parametrize(
    "identity",
    [("/usr/bin/other", OWN_UID), (GNOME_SHELL_EXE, OWN_UID + 1), PermissionError("denied")],
)
def test_untrusted_owner_is_unavailable_and_never_asked_for_focus(
    identity: tuple[str, int] | BaseException,
) -> None:
    bus = FakeBus()
    state = make_reader(bus, FakeIdentity({SHELL_PID: identity})).read()
    assert state == UNAVAILABLE_STATE
    assert bus.focused_calls == 0


def test_pid_zero_is_no_foreground_pid() -> None:
    state = make_reader(FakeBus(focused=0)).read()
    assert state.status is ForegroundStatus.UNAVAILABLE
    assert state.pid is None


def test_bus_error_on_focus_read_is_unavailable() -> None:
    assert make_reader(FakeBus(focused=FocusBusError("timeout"))).read() == UNAVAILABLE_STATE


def test_disabled_reader_never_touches_the_bus() -> None:
    bus = FakeBus()
    assert make_reader(bus, enabled=False).read() == DISABLED_STATE
    assert bus.focused_calls == 0


def test_trusted_owner_is_verified_once_while_its_pid_is_unchanged() -> None:
    identity = FakeIdentity({SHELL_PID: SHELL})
    reader = make_reader(FakeBus(), identity)
    reader.read()
    reader.read()
    assert identity.calls == [SHELL_PID]


def test_cache_is_invalidated_when_the_owner_pid_changes() -> None:
    bus = FakeBus()
    identity = FakeIdentity({SHELL_PID: SHELL, 77: ("/usr/bin/other", OWN_UID)})
    reader = make_reader(bus, identity)
    assert reader.read().status is ForegroundStatus.ACTIVE
    bus.owner = 77
    assert reader.read() == UNAVAILABLE_STATE
    bus.owner = SHELL_PID
    assert reader.read().status is ForegroundStatus.ACTIVE
    assert identity.calls == [SHELL_PID, 77, SHELL_PID]


def test_untrusted_owner_is_rechecked_on_every_read() -> None:
    identity = FakeIdentity({SHELL_PID: ("/usr/bin/other", OWN_UID)})
    reader = make_reader(FakeBus(), identity)
    reader.read()
    reader.read()
    assert identity.calls == [SHELL_PID, SHELL_PID]


def test_gio_bus_reads_focused_pid_through_the_properties_interface() -> None:
    focus = FakeProxy(reply=properties_reply(FOCUSED_PID))
    bus = GioFocusBus(proxy_factory=factory_for({"org.freedesktop.DBus.Properties": focus}))
    assert bus.focused_pid() == FOCUSED_PID
    method, params, timeout_ms = focus.calls[0]
    assert method == "Get"
    assert params.unpack() == (FOCUS_INTERFACE, "FocusedPid")
    assert 0 < timeout_ms <= 500


def test_gio_bus_asks_the_daemon_for_the_owner_pid() -> None:
    daemon = FakeProxy(reply=GLib.Variant("(u)", (SHELL_PID,)))
    bus = GioFocusBus(proxy_factory=factory_for({"org.freedesktop.DBus": daemon}))
    assert bus.owner_pid() == SHELL_PID
    assert daemon.calls[0][1].unpack() == ("io.github.wimm.Focus",)


def test_gio_bus_translates_glib_error() -> None:
    error = glib_error("name has no owner")
    proxy = FakeProxy(error=error)
    bus = GioFocusBus(proxy_factory=factory_for({"org.freedesktop.DBus": proxy}))
    with pytest.raises(FocusBusError):
        bus.owner_pid()


def test_gio_bus_translates_glib_error_while_creating_the_proxy() -> None:
    error = glib_error("no session bus")

    def factory(*, name: str, path: str, interface: str) -> FakeProxy:
        raise error

    with pytest.raises(FocusBusError):
        GioFocusBus(proxy_factory=factory).focused_pid()


def test_gio_bus_rejects_a_reply_that_is_not_a_pid() -> None:
    focus = FakeProxy(reply=GLib.Variant("(v)", (GLib.Variant("s", "x"),)))
    bus = GioFocusBus(proxy_factory=factory_for({"org.freedesktop.DBus.Properties": focus}))
    with pytest.raises(FocusBusError):
        bus.focused_pid()


def test_gio_bus_retries_proxy_creation_after_an_error() -> None:
    error = glib_error("gone")
    attempts: list[int] = []
    good = FakeProxy(reply=properties_reply(FOCUSED_PID))

    def factory(*, name: str, path: str, interface: str) -> FakeProxy:
        attempts.append(1)
        if len(attempts) == 1:
            raise error
        return good

    bus = GioFocusBus(proxy_factory=factory)
    with pytest.raises(FocusBusError):
        bus.focused_pid()
    assert bus.focused_pid() == FOCUSED_PID


def test_from_environment_x11_keeps_the_xprop_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert isinstance(ForegroundReader.from_environment(enabled=True), ForegroundReader)


@pytest.mark.parametrize(("session", "display"), [("wayland", None), (None, "wayland-0")])
def test_from_environment_wayland_picks_the_wayland_reader(
    monkeypatch: pytest.MonkeyPatch, session: str | None, display: str | None
) -> None:
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    if session:
        monkeypatch.setenv("XDG_SESSION_TYPE", session)
    if display:
        monkeypatch.setenv("WAYLAND_DISPLAY", display)
    assert isinstance(ForegroundReader.from_environment(enabled=True), WaylandForegroundReader)


def test_from_environment_wayland_disabled_reads_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert ForegroundReader.from_environment(enabled=False).read() == DISABLED_STATE


def test_open_proxy_never_auto_starts_the_focus_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from gi.repository import Gio

    seen: list[Any] = []

    def capture(*args: Any) -> str:
        seen.append(args[1])
        return "proxy"

    monkeypatch.setattr(Gio.DBusProxy, "new_for_bus_sync", capture)

    open_proxy(name="io.github.wimm.Focus", path="/io/github/wimm/Focus", interface="x.y")

    # Auto-start would make the sampler worker wait for D-Bus activation, up to 25 s.
    assert seen[0] & Gio.DBusProxyFlags.DO_NOT_AUTO_START
