import json
from pathlib import Path
from typing import Any, Protocol

from gi.repository import Gio, GLib

from wimm import __version__
from wimm.core.disk_wire import disk_report_to_json
from wimm.model.disk import DiskReport
from wimm.model.enums import SCHEMA_VERSION
from wimm.model.snapshot import Snapshot
from wimm.snapshot_redaction import redacted_snapshot_json

INTERFACE = "io.github.wimm.Inspector1"
OBJECT_PATH = "/io/github/wimm/Inspector"
XML_FILE = "io.github.wimm.Inspector1.xml"
INSTALLED_XML_DIRECTORY = Path("/usr/share/where-is-my-memory/dbus")
NOT_READY = "io.github.wimm.Error.NotReady"
# Before the first scan there is no report: the reply says so instead of failing.
DISK_REPORT = json.dumps({"schema": SCHEMA_VERSION, "available": False})


class SnapshotSource(Protocol):
    def snapshot(self) -> Snapshot | None: ...

    def disk_report(self) -> DiskReport | None: ...


def introspection_path() -> Path:
    """Prefer source-tree XML in development, otherwise the Debian data directory."""
    source = Path(__file__).resolve().parents[3] / "data" / "dbus" / XML_FILE
    return source if source.is_file() else INSTALLED_XML_DIRECTORY / XML_FILE


class Inspector:
    def __init__(self, *, connection: Gio.DBusConnection, service: SnapshotSource) -> None:
        self._connection, self._service = connection, service
        self._info = Gio.DBusNodeInfo.new_for_xml(
            xml_data=introspection_path().read_text(encoding="utf-8")
        )
        self._registration = connection.register_object(
            object_path=OBJECT_PATH,
            interface_info=self._info.interfaces[0],
            method_call_closure=self._method_call,
            get_property_closure=self._get_property,
            set_property_closure=None,
        )

    def _method_call(self, *args: Any) -> None:
        _, _, _, _, method, _, invocation = args
        if method == "GetDiskReport":
            report = self._service.disk_report()
            text = DISK_REPORT if report is None else disk_report_to_json(report=report)
            invocation.return_value(GLib.Variant("(s)", (text,)))
            return
        snapshot = self._service.snapshot()
        if snapshot is None:
            invocation.return_dbus_error(NOT_READY, "Snapshot is not ready")
            return
        invocation.return_value(GLib.Variant("(s)", (redacted_snapshot_json(snapshot=snapshot),)))

    def _get_property(self, *args: Any) -> GLib.Variant:
        return GLib.Variant("s", __version__)

    def close(self) -> None:
        if self._registration:
            self._connection.unregister_object(registration_id=self._registration)
            self._registration = 0
