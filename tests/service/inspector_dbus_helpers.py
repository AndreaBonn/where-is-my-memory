import os
import signal
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest
from gi.repository import Gio, GLib

from tests.core.assemble_helpers import build_input, draft, pair
from tests.service.test_app_service import spin_until
from wimm.core.assemble import assemble_snapshot
from wimm.model.disk import DiskReport
from wimm.model.enums import Category
from wimm.model.snapshot import Snapshot
from wimm.service.inspector_dbus import INTERFACE, OBJECT_PATH


class SnapshotSource:
    current: Snapshot | None = None
    report: DiskReport | None = None

    def disk_report(self) -> DiskReport | None:
        return self.report

    def snapshot(self) -> Snapshot | None:
        return self.current


def sensitive_snapshot() -> Snapshot:
    proc, decision = pair(20, Category.DEV_PROCESS)
    proc = replace(
        proc,
        cmdline=(
            "node",
            "--token=abc",
            "--password",
            "two words",
            "--port=8000",
            "Authorization: Bearer abc",
            "https://user:pass@host/x",
        ),
    )
    return assemble_snapshot(inputs=build_input([draft("g", pids=(20,))], pairs=[(proc, decision)]))


@pytest.fixture
def private_bus_address() -> Iterator[str]:
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
    try:
        yield address
    finally:
        os.kill(int(pid), signal.SIGTERM)


@pytest.fixture
def private_connections(
    private_bus_address: str,
) -> Iterator[tuple[Gio.DBusConnection, Gio.DBusConnection]]:
    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    connections: list[Gio.DBusConnection] = []
    try:
        for _ in range(2):
            connections.append(
                Gio.DBusConnection.new_for_address_sync(
                    address=private_bus_address,
                    flags=flags,
                    observer=None,
                    cancellable=None,
                )
            )
        yield connections[0], connections[1]
    finally:
        for connection in connections:
            connection.close_sync(cancellable=None)


def call(
    connections: tuple[Gio.DBusConnection, Gio.DBusConnection],
    method: str,
    interface: str = INTERFACE,
    parameters: GLib.Variant | None = None,
) -> GLib.Variant:
    server, client = connections
    results: list[Any] = []

    def complete(connection: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
        try:
            results.append(connection.call_finish(result))
        except GLib.Error as error:
            results.append(error)

    client.call(
        bus_name=server.get_unique_name(),
        object_path=OBJECT_PATH,
        interface_name=interface,
        method_name=method,
        parameters=parameters,
        reply_type=None,
        flags=Gio.DBusCallFlags.NONE,
        timeout_msec=3000,
        cancellable=None,
        callback=complete,
    )
    spin_until(predicate=lambda: bool(results))
    if isinstance(results[0], GLib.Error):
        raise results[0]
    return cast(GLib.Variant, results[0])
