import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from time import monotonic, sleep

import pytest
from gi.repository import Gio, GLib

from tests.service.inspector_dbus_helpers import private_bus_address as private_bus_address
from wimm.cli_status import EXIT_OK
from wimm.first_run import mark_welcomed
from wimm.model.snapshot import Snapshot
from wimm.serialize import snapshot_from_json
from wimm.service.inspector_dbus import INTERFACE, OBJECT_PATH

APP_ID = "io.github.wimm.StatusCliTest"
ACTIONS_INTERFACE = "org.gtk.Actions"
ACTIONS_PATH = "/" + APP_ID.replace(".", "/")  # GApplication derives it from the id
REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_TIMEOUT_S = 30
READY_TIMEOUT_S = 20
EXIT_TIMEOUT_S = 10
POLL_S = 0.05
CALL_TIMEOUT_MS = 2000


def headless_environment(*, bus_address: str) -> dict[str, str]:
    """Isolated HOME/XDG (set by conftest), the private bus and no display at all."""
    environment = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": bus_address, "WIMM_APP_ID": APP_ID}
    for variable in ("DISPLAY", "WAYLAND_DISPLAY"):
        environment.pop(variable, None)
    return environment


def run_status_json(*, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args=[sys.executable, "-m", "wimm", "status", "--json"],
        env=environment,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=CLI_TIMEOUT_S,
    )


def bus_connection(*, address: str) -> Gio.DBusConnection:
    return Gio.DBusConnection.new_for_address_sync(
        address,
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None,
        None,
    )


def get_snapshot(*, connection: Gio.DBusConnection) -> Snapshot | None:
    """The instance's snapshot over D-Bus, or None while it is absent or NotReady."""
    try:
        reply = connection.call_sync(
            APP_ID,
            OBJECT_PATH,
            INTERFACE,
            "GetSnapshot",
            None,
            None,
            Gio.DBusCallFlags.NO_AUTO_START,
            CALL_TIMEOUT_MS,
            None,
        )
    except GLib.Error:
        return None
    return snapshot_from_json(text=reply.unpack()[0])


def wait_for_snapshot(
    *, connection: Gio.DBusConnection, process: subprocess.Popen[str]
) -> Snapshot:
    deadline = monotonic() + READY_TIMEOUT_S
    while monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"The instance exited early with {process.returncode}")
        snapshot = get_snapshot(connection=connection)
        if snapshot is not None:
            return snapshot
        sleep(POLL_S)
    raise AssertionError("The Inspector never answered GetSnapshot")


def request_quit(*, connection: Gio.DBusConnection) -> None:
    connection.call_sync(
        APP_ID,
        ACTIONS_PATH,
        ACTIONS_INTERFACE,
        "Activate",
        GLib.Variant("(sava{sv})", ("quit", [], {})),
        None,
        Gio.DBusCallFlags.NO_AUTO_START,
        CALL_TIMEOUT_MS,
        None,
    )


@pytest.fixture
def running_instance(private_bus_address: str) -> Iterator[subprocess.Popen[str]]:
    mark_welcomed(state_dir=Path(os.environ["XDG_STATE_HOME"]) / "where-is-my-memory")
    process = subprocess.Popen(
        args=[sys.executable, "-m", "wimm", "--background"],
        env=headless_environment(bus_address=private_bus_address),
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=EXIT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@pytest.mark.integration
@pytest.mark.dbus
def test_status_json_without_instance_samples_locally_and_exits_zero(
    private_bus_address: str,
) -> None:
    result = run_status_json(environment=headless_environment(bus_address=private_bus_address))

    assert result.returncode == EXIT_OK, result.stderr
    snapshot = snapshot_from_json(text=result.stdout)
    assert snapshot.taken_at.tzinfo is not None
    assert json.loads(result.stdout)["taken_at"]


@pytest.mark.integration
@pytest.mark.dbus
def test_status_json_with_running_instance_returns_the_instance_snapshot(
    private_bus_address: str, running_instance: subprocess.Popen[str]
) -> None:
    connection = bus_connection(address=private_bus_address)
    try:
        wait_for_snapshot(connection=connection, process=running_instance)

        before = get_snapshot(connection=connection)
        result = run_status_json(environment=headless_environment(bus_address=private_bus_address))
        after = get_snapshot(connection=connection)

        assert result.returncode == EXIT_OK, result.stderr
        assert before is not None and after is not None
        snapshot = snapshot_from_json(text=result.stdout)
        # A local cycle would carry its own monitor_started_at and a fresh taken_at; the
        # instance's snapshot is one of the two it served around the CLI call.
        assert snapshot.monitor_started_at == before.monitor_started_at
        assert snapshot.taken_at in (before.taken_at, after.taken_at)

        request_quit(connection=connection)
        assert running_instance.wait(timeout=EXIT_TIMEOUT_S) == 0
    finally:
        connection.close_sync(None)
