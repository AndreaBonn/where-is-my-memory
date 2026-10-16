import json
from pathlib import Path
from typing import Any, Protocol

from gi.repository import Gio, GLib

from wimm import __version__
from wimm.model.snapshot import Snapshot
from wimm.redaction import REDACTED, SECRET_ARGUMENT, redact_text
from wimm.serialize import snapshot_to_json

INTERFACE = "io.github.wimm.Inspector1"
OBJECT_PATH = "/io/github/wimm/Inspector"
XML_FILE = "io.github.wimm.Inspector1.xml"
INSTALLED_XML_DIRECTORY = Path("/usr/share/where-is-my-memory/dbus")
NOT_READY = "io.github.wimm.Error.NotReady"
DISK_REPORT = '{"schema":1,"available":false}'


class SnapshotSource(Protocol):
    def snapshot(self) -> Snapshot | None: ...


def introspection_path() -> Path:
    """Prefer source-tree XML in development, otherwise the Debian data directory."""
    source = Path(__file__).resolve().parents[3] / "data" / "dbus" / XML_FILE
    return source if source.is_file() else INSTALLED_XML_DIRECTORY / XML_FILE


def redact_cmdline(*, arguments: list[str]) -> list[str]:
    result: list[str] = []
    pending = False
    for argument in arguments:
        if pending:
            result.append(REDACTED)
            pending = False
            continue
        match = SECRET_ARGUMENT.search(string=f"{argument} {REDACTED}")
        if match is None:
            result.append(redact_text(text=argument))
            continue
        prefix = match["prefix"]
        pending = prefix.rstrip() == argument
        result.append(argument if pending else argument[: match.start()] + prefix + REDACTED)
    return result


def snapshot_for_dbus(*, snapshot: Snapshot) -> str:
    data = json.loads(snapshot_to_json(snapshot=snapshot))
    for group in data["groups"]:
        for member in group["members"]:
            if "cmdline" in member:
                member["cmdline"] = redact_cmdline(arguments=member["cmdline"])
    return json.dumps(data, ensure_ascii=False)


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
            invocation.return_value(GLib.Variant("(s)", (DISK_REPORT,)))
            return
        snapshot = self._service.snapshot()
        if snapshot is None:
            invocation.return_dbus_error(NOT_READY, "Snapshot is not ready")
            return
        invocation.return_value(GLib.Variant("(s)", (snapshot_for_dbus(snapshot=snapshot),)))

    def _get_property(self, *args: Any) -> GLib.Variant:
        return GLib.Variant("s", __version__)

    def close(self) -> None:
        if self._registration:
            self._connection.unregister_object(registration_id=self._registration)
            self._registration = 0
