import json
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from gi.repository import Gio, GLib

from tests.core.assemble_helpers import build_input, draft, pair
from tests.core.disk_helpers import MB, cache, devdir, report
from tests.core.helpers import process
from tests.service.dbus_helpers import stop_application, wait_for_actions
from tests.service.test_app_service import spin_until
from wimm import __version__
from wimm.core.assemble import assemble_snapshot
from wimm.core.disk_wire import disk_report_from_json
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import Category
from wimm.model.snapshot import ProcessMember, Snapshot
from wimm.serialize import snapshot_from_json
from wimm.service.inspector_dbus import INTERFACE, OBJECT_PATH, Inspector, snapshot_for_dbus

# Allow Gio.Application startup and the first sample on a private bus.
APP_STARTUP_TIMEOUT_S = 45


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


def test_snapshot_redaction_preserves_model_and_json_contract() -> None:
    snapshot = sensitive_snapshot()
    redacted = snapshot_from_json(text=snapshot_for_dbus(snapshot=snapshot))
    member = redacted.groups[0].members[0]
    original = snapshot.groups[0].members[0]
    assert isinstance(member, ProcessMember)
    assert isinstance(original, ProcessMember)
    assert member.cmdline == (
        "node",
        "--token=[REDACTED]",
        "--password",
        "[REDACTED]",
        "--port=8000",
        "Authorization: Bearer [REDACTED]",
        "https://user:[REDACTED]@host/x",
    )
    assert original.cmdline[1] == "--token=abc"
    assert process().cmdline is None


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


@pytest.mark.dbus
def test_inspector_exports_only_read_only_members(private_connections: Any) -> None:
    source = SnapshotSource()
    inspector = Inspector(connection=private_connections[0], service=source)
    try:
        with pytest.raises(GLib.Error, match=r"io.github.wimm.Error.NotReady"):
            call(connections=private_connections, method="GetSnapshot")
        source.current = sensitive_snapshot()
        text = call(connections=private_connections, method="GetSnapshot").unpack()[0]
        member = snapshot_from_json(text=text).groups[0].members[0]
        assert isinstance(member, ProcessMember)
        assert member.cmdline[1] == "--token=[REDACTED]"
        assert member.cmdline[-2:] == (
            "Authorization: Bearer [REDACTED]",
            "https://user:[REDACTED]@host/x",
        )
        assert json.loads(
            call(connections=private_connections, method="GetDiskReport").unpack()[0]
        ) == {
            "schema": 1,
            "available": False,
        }
        xml = call(
            connections=private_connections,
            method="Introspect",
            interface="org.freedesktop.DBus.Introspectable",
        ).unpack()[0]
        info = Gio.DBusNodeInfo.new_for_xml(xml_data=xml).lookup_interface(name=INTERFACE)
        assert info is not None
        assert {item.name for item in info.methods} == {"GetSnapshot", "GetDiskReport"}
        assert {item.name for item in info.properties} == {"Version"}
        assert not info.signals
        version = call(
            connections=private_connections,
            method="Get",
            interface="org.freedesktop.DBus.Properties",
            parameters=GLib.Variant("(ss)", (INTERFACE, "Version")),
        ).unpack()[0]
        assert version == __version__
    finally:
        inspector.close()


@pytest.mark.dbus
def test_get_disk_report_returns_json_the_wire_decoder_parses(
    private_connections: Any,
) -> None:
    source = SnapshotSource()
    source.report = report(
        caches=(cache(kind=CacheKind.UV, size=3 * MB),),
        devdirs=(devdir(path="/home/u/p/node_modules", size=5 * MB),),
    )
    inspector = Inspector(connection=private_connections[0], service=source)
    try:
        text = call(connections=private_connections, method="GetDiskReport").unpack()[0]
        assert disk_report_from_json(text=text) == source.report
    finally:
        inspector.close()


@pytest.mark.dbus
def test_application_exports_only_its_three_actions_and_handles_remote_group(
    private_bus_address: str,
    private_connections: tuple[Gio.DBusConnection, Gio.DBusConnection],
    tmp_path: Path,
) -> None:
    environment = {
        **os.environ,
        "DBUS_SESSION_BUS_ADDRESS": private_bus_address,
        "WIMM_APP_ID": "io.github.wimm.Test",
        "GSETTINGS_BACKEND": "memory",
        "XDG_RUNTIME_DIR": str(tmp_path),
    }
    # No display: the remote --group must not pop a real window on the developer's screen,
    # and the primary must survive a window that cannot open.
    for variable in ("DISPLAY", "WAYLAND_DISPLAY"):
        environment.pop(variable, None)
    log_path = tmp_path / "application.log"
    with log_path.open(mode="w") as log:
        application = subprocess.Popen(
            args=[sys.executable, "-m", "wimm", "--background"],
            start_new_session=True,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=log,
        )
        try:
            client = private_connections[1]
            actions = wait_for_actions(connection=client)
            assert set(actions) == {"quit", "open-group", "snooze-group"}
            remote = subprocess.run(
                args=[sys.executable, "-m", "wimm", "--group", "example"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=APP_STARTUP_TIMEOUT_S,
                check=False,
            )
            assert remote.returncode == 0, remote.stderr
            assert application.poll() is None
            client.call_sync(
                bus_name="io.github.wimm.Test",
                object_path="/io/github/wimm/Test",
                interface_name="org.gtk.Actions",
                method_name="Activate",
                parameters=GLib.Variant("(sava{sv})", ("quit", [], {})),
                reply_type=None,
                flags=Gio.DBusCallFlags.NONE,
                timeout_msec=3000,
                cancellable=None,
            )
            assert application.wait(timeout=5) == 0
        finally:
            stop_application(application=application)
    written = log_path.read_text()
    assert "Window requested for group example" in written
    assert "Cannot open the window" in written


def test_inspection_xml_has_exact_read_only_contract() -> None:
    from wimm.service.inspector_dbus import introspection_path

    path = introspection_path()
    info = Gio.DBusNodeInfo.new_for_xml(xml_data=path.read_text()).lookup_interface(name=INTERFACE)
    assert info is not None
    assert {method.name for method in info.methods} == {"GetSnapshot", "GetDiskReport"}
    assert [(prop.name, prop.signature, prop.flags) for prop in info.properties] == [
        ("Version", "s", Gio.DBusPropertyInfoFlags.READABLE),
    ]
    assert not info.signals


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (
            ["node", "--api-key=a b", "--port", "8000"],
            ["node", "--api-key=[REDACTED]", "--port", "8000"],
        ),
        (
            ["node", "--secret", "a b", "--token=abc"],
            ["node", "--secret", "[REDACTED]", "--token=[REDACTED]"],
        ),
        (["node", "--port=8000"], ["node", "--port=8000"]),
    ],
)
def test_redact_cmdline_handles_spaces_and_separate_values(
    arguments: list[str],
    expected: list[str],
) -> None:
    from wimm.service.inspector_dbus import redact_cmdline

    assert redact_cmdline(arguments=arguments) == expected
