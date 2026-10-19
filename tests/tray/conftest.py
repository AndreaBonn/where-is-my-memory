import os
import signal
import subprocess
from collections.abc import Iterator
from typing import Any, cast

import pytest
from gi.repository import Gio, GLib

from tests.service.test_app_service import spin_until

CALL_TIMEOUT_MS = 3000


class Bus:
    """A server connection (the code under test) and a client connection on a private bus."""

    def __init__(self, *, server: Gio.DBusConnection, client: Gio.DBusConnection) -> None:
        self.server, self.client = server, client

    def call(
        self,
        *,
        path: str,
        interface: str,
        method: str,
        parameters: GLib.Variant | None = None,
    ) -> GLib.Variant:
        results: list[Any] = []

        def complete(connection: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
            try:
                results.append(connection.call_finish(res=result))
            except GLib.Error as error:
                results.append(error)

        self.client.call(
            bus_name=self.server.get_unique_name(),
            object_path=path,
            interface_name=interface,
            method_name=method,
            parameters=parameters,
            reply_type=None,
            flags=Gio.DBusCallFlags.NONE,
            timeout_msec=CALL_TIMEOUT_MS,
            cancellable=None,
            callback=complete,
        )
        spin_until(predicate=lambda: bool(results))
        if isinstance(results[0], GLib.Error):
            raise results[0]
        return cast(GLib.Variant, results[0])

    def get(self, *, path: str, interface: str, name: str) -> Any:
        reply = self.call(
            path=path,
            interface="org.freedesktop.DBus.Properties",
            method="Get",
            parameters=GLib.Variant("(ss)", (interface, name)),
        )
        return reply.unpack()[0]

    def subscribe(self, *, path: str, interface: str, member: str) -> list[Any]:
        """Collect the arguments of every matching signal; ordered before later replies."""
        received: list[Any] = []

        def collect(*args: Any) -> None:
            received.append(args[5].unpack())

        self.client.signal_subscribe(
            sender=self.server.get_unique_name(),
            interface_name=interface,
            member=member,
            object_path=path,
            arg0=None,
            flags=Gio.DBusSignalFlags.NONE,
            callback=collect,
        )
        # signal_subscribe sends AddMatch without waiting: a signal from the other connection
        # could reach the daemon first and be lost. The daemon handles one connection's
        # messages in order, so once this round trip returns the match is in place.
        self.client.call_sync(
            bus_name="org.freedesktop.DBus",
            object_path="/org/freedesktop/DBus",
            interface_name="org.freedesktop.DBus.Peer",
            method_name="Ping",
            parameters=None,
            reply_type=None,
            flags=Gio.DBusCallFlags.NONE,
            timeout_msec=CALL_TIMEOUT_MS,
            cancellable=None,
        )
        return received


@pytest.fixture
def bus() -> Iterator[Bus]:
    result = subprocess.run(
        args=["/usr/bin/dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode:
        pytest.skip(f"Private D-Bus unavailable: {result.stderr.strip()}")
    address, pid = result.stdout.splitlines()
    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    connections = [
        Gio.DBusConnection.new_for_address_sync(
            address=address, flags=flags, observer=None, cancellable=None
        )
        for _ in range(2)
    ]
    try:
        yield Bus(server=connections[0], client=connections[1])
    finally:
        for connection in connections:
            connection.close_sync(cancellable=None)
        os.kill(int(pid), signal.SIGTERM)
