import logging
from typing import Any

import pytest
from gi.repository import Gio, GLib

from tests.service.test_app_service import spin_until
from tests.tray.conftest import Bus
from wimm.tray.status_notifier import WATCHER_NAME, WATCHER_PATH
from wimm.tray.watcher import WATCHER_ABSENT_MS, TrayWatcher, WatcherCallbacks

SHORT_ABSENCE_MS = 150
CALL_FLAGS = Gio.DBusCallFlags.NONE
REQUEST_NAME_OWNER = (1,)
WATCHER_XML = """
<node><interface name="org.kde.StatusNotifierWatcher">
  <method name="RegisterStatusNotifierItem">
    <arg type="s" name="service" direction="in"/>
  </method>
</interface></node>
"""


class FakeWatcher:
    """Owns the watcher name on the client connection and counts registrations."""

    def __init__(self, *, bus: Bus) -> None:
        self._bus = bus
        self.registrations: list[str] = []
        self.fail = False
        info = Gio.DBusNodeInfo.new_for_xml(xml_data=WATCHER_XML)
        self._object = bus.client.register_object(
            object_path=WATCHER_PATH,
            interface_info=info.interfaces[0],
            method_call_closure=self._method_call,
            get_property_closure=None,
            set_property_closure=None,
        )

    def _method_call(self, *args: Any) -> None:
        self.registrations.append(args[5].unpack()[0])
        if self.fail:
            args[6].return_dbus_error("org.freedesktop.DBus.Error.Failed", "refused")
        else:
            args[6].return_value(None)

    def _bus_call(self, *, method: str, parameters: GLib.Variant) -> tuple[int]:
        reply = self._bus.client.call_sync(
            bus_name="org.freedesktop.DBus",
            object_path="/org/freedesktop/DBus",
            interface_name="org.freedesktop.DBus",
            method_name=method,
            parameters=parameters,
            reply_type=None,
            flags=CALL_FLAGS,
            timeout_msec=3000,
            cancellable=None,
        )
        values: tuple[int] = reply.unpack()
        return values

    def appear(self) -> None:
        assert (
            self._bus_call(method="RequestName", parameters=GLib.Variant("(su)", (WATCHER_NAME, 0)))
            == REQUEST_NAME_OWNER
        )

    def vanish(self) -> None:
        self._bus_call(method="ReleaseName", parameters=GLib.Variant("(s)", (WATCHER_NAME,)))


class Events:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.callbacks = WatcherCallbacks(
            on_appeared=lambda: self.log.append("appeared"),
            on_absent=lambda: self.log.append("absent"),
        )

    def count(self, name: str) -> int:
        return self.log.count(name)


def wait_past_timeout(*, timeout_ms: int = SHORT_ABSENCE_MS) -> None:
    """Return once a timer of ``timeout_ms`` started now has fired.

    A watcher timer of the same length created earlier is due before this one, so when this
    returns the watcher timer has fired already unless it was stopped.
    """
    fired: list[bool] = []

    def mark() -> bool:
        fired.append(True)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(timeout_ms, mark)
    spin_until(predicate=lambda: bool(fired))


def start(bus: Bus, events: Events, *, absent_after_ms: int = SHORT_ABSENCE_MS) -> TrayWatcher:
    return TrayWatcher(
        connection=bus.server, callbacks=events.callbacks, absent_after_ms=absent_after_ms
    )


@pytest.mark.dbus
def test_a_watcher_on_the_bus_is_reported_as_appeared(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    fake.appear()
    events = Events()
    watcher = start(bus, events)
    try:
        spin_until(predicate=lambda: events.count("appeared") == 1)
        assert events.count("absent") == 0
    finally:
        watcher.close()


@pytest.mark.dbus
def test_every_reappearance_of_the_watcher_calls_on_appeared_again(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    fake.appear()
    events = Events()
    watcher = start(bus, events)
    try:
        spin_until(predicate=lambda: events.count("appeared") == 1)
        fake.vanish()
        fake.appear()
        spin_until(predicate=lambda: events.count("appeared") == 2)
        assert events.count("absent") == 0  # the host was never reported missing
    finally:
        watcher.close()


@pytest.mark.dbus
def test_without_a_watcher_absence_is_reported_once_after_the_timeout(bus: Bus) -> None:
    events = Events()
    watcher = start(bus, events)
    try:
        spin_until(predicate=lambda: events.count("absent") == 1)
        assert events.count("appeared") == 0
    finally:
        watcher.close()


@pytest.mark.dbus
def test_absence_is_reported_once_however_often_the_watcher_comes_back(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    events = Events()
    watcher = start(bus, events)
    try:
        spin_until(predicate=lambda: events.count("absent") == 1)
        fake.appear()
        spin_until(predicate=lambda: events.count("appeared") == 1)
        fake.vanish()
        fake.appear()
        spin_until(predicate=lambda: events.count("appeared") == 2)
        assert events.count("absent") == 1
    finally:
        watcher.close()


@pytest.mark.dbus
def test_a_watcher_that_appears_before_the_timeout_never_reports_absence(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    events = Events()
    watcher = start(bus, events)
    try:
        fake.appear()
        spin_until(predicate=lambda: events.count("appeared") == 1)
        wait_past_timeout()  # the absence timer was due before this returns
        assert events.log == ["appeared"]
    finally:
        watcher.close()


@pytest.mark.dbus
def test_close_stops_the_timer_so_no_absence_is_reported(bus: Bus) -> None:
    quiet = Events()
    start(bus, quiet).close()
    reporting = Events()
    watcher = start(bus, reporting)  # same timeout, not closed: reports absence
    try:
        spin_until(predicate=lambda: reporting.count("absent") == 1)
        wait_past_timeout()
        assert quiet.log == []
        assert reporting.log == ["absent"]
    finally:
        watcher.close()


@pytest.mark.dbus
def test_close_stops_the_watch_and_is_idempotent(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    fake.appear()
    events = Events()
    watcher = start(bus, events)
    spin_until(predicate=lambda: events.count("appeared") == 1)  # followed before close
    watcher.close()
    watcher.close()
    fake.vanish()
    fake.appear()
    wait_past_timeout()
    assert events.log == ["appeared"]


@pytest.mark.dbus
def test_a_callback_that_raises_is_logged_and_the_watcher_stays_alive(
    bus: Bus, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeWatcher(bus=bus)
    calls: list[str] = []

    def failing() -> None:
        calls.append("appeared")
        raise RuntimeError("boom")

    callbacks = WatcherCallbacks(on_appeared=failing, on_absent=lambda: calls.append("absent"))
    with caplog.at_level(logging.ERROR):
        watcher = TrayWatcher(connection=bus.server, callbacks=callbacks, absent_after_ms=10_000)
        try:
            fake.appear()
            spin_until(predicate=lambda: len(calls) == 1)
            assert "Watcher callback failed" in caplog.text
            fake.vanish()
            fake.appear()
            spin_until(predicate=lambda: len(calls) == 2)  # still watching after the failure
        finally:
            watcher.close()
    assert calls == ["appeared", "appeared"]


def test_the_default_absence_timeout_is_ten_seconds() -> None:
    assert WATCHER_ABSENT_MS == 10_000
