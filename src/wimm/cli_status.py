"""``wimm status``: the state on the terminal, without a window and without GTK.

Only Gio is used (never Gtk or Adw), so the command works over SSH. The data comes from the
running instance when there is one (Q6=A) and from a single sampling cycle otherwise.
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from wimm.cli_status_text import render_status
from wimm.i18n import _
from wimm.model.snapshot import Snapshot
from wimm.serialize import SnapshotFormatError, snapshot_from_json
from wimm.snapshot_redaction import redacted_snapshot_json

EXIT_OK = 0
EXIT_NO_STATE = 3
PROXY_TIMEOUT_MS = 2000
APPLICATION_ID = "io.github.wimm.WhereIsMyMemory"
COMMAND = "status"
APP_ID_VARIABLE = "WIMM_APP_ID"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StatusSources:
    """Where the snapshot comes from: the running instance first, then local sampling."""

    from_instance: Callable[[], Snapshot | None]
    sample_locally: Callable[[], Snapshot | None]


def connect_instance() -> Any | None:
    """Return a proxy of the running instance's inspector, or None when nothing answers."""
    from gi.repository import Gio, GLib

    from wimm.service.inspector_dbus import INTERFACE, OBJECT_PATH

    flags = (
        Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES
        | Gio.DBusProxyFlags.DO_NOT_CONNECT_SIGNALS
        | Gio.DBusProxyFlags.DO_NOT_AUTO_START
    )
    try:
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            flags,
            None,
            os.environ.get(APP_ID_VARIABLE, APPLICATION_ID),
            OBJECT_PATH,
            INTERFACE,
            None,
        )
    except GLib.Error as error:
        LOGGER.debug("No session bus for the inspector: %s", error)
        return None


def snapshot_from_instance(
    *, connect: Callable[[], Any | None] = connect_instance
) -> Snapshot | None:
    """Ask the running instance for its snapshot; any failure (absent, NotReady) gives None."""
    from gi.repository import Gio, GLib

    proxy = connect()
    if proxy is None:
        return None
    try:
        reply = proxy.call_sync(
            "GetSnapshot", None, Gio.DBusCallFlags.NO_AUTO_START, PROXY_TIMEOUT_MS, None
        )
        return snapshot_from_json(text=reply.unpack()[0])
    except (GLib.Error, SnapshotFormatError) as error:
        LOGGER.debug("The running instance gave no usable snapshot: %s", error)
        return None


def sample_locally() -> Snapshot | None:
    """Run one sampling cycle in this process; None when the system cannot be read."""
    from pathlib import Path

    from wimm.config import load_config
    from wimm.paths import default_user_paths
    from wimm.service.sampler import Sampler, default_collectors, default_environment

    try:
        paths = default_user_paths()
        environment = default_environment(paths=paths)
        config = load_config(paths=paths, home=Path.home()).config
        collectors = default_collectors(environment=environment)
        return Sampler(collectors=collectors, environment=environment, config=config).run_cycle()
    except Exception as error:
        print(f"wimm: {error}", file=sys.stderr)
        return None


def _parse(*, arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=" ".join(("wimm", COMMAND)), description=_("Mostra lo stato")
    )
    parser.add_argument("--json", action="store_true", help=_("Stampa lo stato come JSON"))
    return parser.parse_args(arguments)


def run_status(*, arguments: list[str], sources: StatusSources | None = None) -> int:
    """Print the state and return the exit code: 0 on success, 3 when there is no state."""
    from wimm.language_switch import apply_startup_language

    apply_startup_language()
    options = _parse(arguments=arguments)
    chosen = sources or StatusSources(
        from_instance=snapshot_from_instance, sample_locally=sample_locally
    )
    snapshot = chosen.from_instance() or chosen.sample_locally()
    if snapshot is None:
        print(_("Nessuno stato disponibile"), file=sys.stderr)
        return EXIT_NO_STATE
    print(
        redacted_snapshot_json(snapshot=snapshot)
        if options.json
        else render_status(snapshot=snapshot)
    )
    return EXIT_OK
