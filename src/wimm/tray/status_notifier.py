import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

LOGGER = logging.getLogger(__name__)

SNI_IFACE = "org.kde.StatusNotifierItem"
SNI_OBJECT_PATH = "/StatusNotifierItem"
MENU_OBJECT_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_ID = "io.github.wimm.WhereIsMyMemory"
CATEGORY = "SystemServices"
STATUS_ACTIVE = "Active"
ICON_NORMAL = "wimm-normal-symbolic"
LABEL_GUIDE = "88,8 GB inattivi"
INSTALLED_ICON_DIRECTORY = Path("/usr/share/icons")
WATCHER_TIMEOUT_MS = 2000

INTROSPECTION = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
    </method>
    <method name="Scroll">
      <arg type="i" name="delta" direction="in"/>
      <arg type="s" name="orientation" direction="in"/>
    </method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="XAyatanaLabel" type="s" access="read"/>
    <property name="XAyatanaLabelGuide" type="s" access="read"/>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg type="s" name="status"/></signal>
    <signal name="XAyatanaNewLabel">
      <arg type="s" name="label"/>
      <arg type="s" name="guide"/>
    </signal>
  </interface>
</node>
"""


def icon_theme_path() -> str:
    """Prefer the source-tree icons in development, otherwise the system directory."""
    source = Path(__file__).resolve().parents[3] / "data" / "icons"
    return str(source if source.is_dir() else INSTALLED_ICON_DIRECTORY)


class StatusNotifierItem:
    """Serve one StatusNotifierItem and register it with the watcher."""

    def __init__(
        self,
        *,
        connection: Gio.DBusConnection,
        on_activate: Callable[[], None],
        on_secondary_activate: Callable[[], None],
        title: str,
    ) -> None:
        self._connection = connection
        self._callbacks = {"Activate": on_activate, "SecondaryActivate": on_secondary_activate}
        self._title, self._tooltip = title, ""
        self._status, self._icon_name = STATUS_ACTIVE, ICON_NORMAL
        self._label, self._guide = "", LABEL_GUIDE
        self._theme_path = icon_theme_path()
        info = Gio.DBusNodeInfo.new_for_xml(xml_data=INTROSPECTION)
        self._registration = connection.register_object(
            object_path=SNI_OBJECT_PATH,
            interface_info=info.interfaces[0],
            method_call_closure=self._method_call,
            get_property_closure=self._get_property,
            set_property_closure=None,
        )

    @property
    def icon_name(self) -> str:
        return self._icon_name

    @icon_name.setter
    def icon_name(self, value: str) -> None:
        if value != self._icon_name:
            self._icon_name = value
            self._emit(signal="NewIcon")

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        if value != self._status:
            self._status = value
            self._emit(signal="NewStatus", parameters=GLib.Variant("(s)", (value,)))

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        if value != self._title:
            self._title = value
            self._emit(signal="NewTitle")

    @property
    def tooltip(self) -> str:
        return self._tooltip

    @tooltip.setter
    def tooltip(self, value: str) -> None:
        if value != self._tooltip:
            self._tooltip = value
            self._emit(signal="NewToolTip")

    @property
    def label(self) -> str:
        return self._label

    @label.setter
    def label(self, value: str) -> None:
        if value != self._label:
            self._label = value
            self._emit_label()

    @property
    def guide(self) -> str:
        return self._guide

    @guide.setter
    def guide(self, value: str) -> None:
        if value != self._guide:
            self._guide = value
            self._emit_label()

    def register_with_watcher(self) -> None:
        """Ask the watcher to show this item; the outcome is only logged."""
        self._connection.call(
            bus_name=WATCHER_NAME,
            object_path=WATCHER_PATH,
            interface_name=WATCHER_NAME,
            method_name="RegisterStatusNotifierItem",
            # The unique name makes the watcher use the default /StatusNotifierItem path.
            parameters=GLib.Variant("(s)", (self._connection.get_unique_name(),)),
            reply_type=None,
            flags=Gio.DBusCallFlags.NONE,
            timeout_msec=WATCHER_TIMEOUT_MS,
            cancellable=None,
            callback=self._registered,
        )

    def close(self) -> None:
        if self._registration:
            self._connection.unregister_object(registration_id=self._registration)
            self._registration = 0

    def _registered(self, connection: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
        try:
            connection.call_finish(res=result)
        except GLib.Error as error:
            LOGGER.warning("StatusNotifierWatcher registration failed: %s", error.message)
            return
        LOGGER.info("Registered with StatusNotifierWatcher")

    def _emit_label(self) -> None:
        parameters = GLib.Variant("(ss)", (self._label, self._guide))
        self._emit(signal="XAyatanaNewLabel", parameters=parameters)

    def _emit(self, *, signal: str, parameters: GLib.Variant | None = None) -> None:
        if not self._registration:
            return
        self._connection.emit_signal(
            destination_bus_name=None,
            object_path=SNI_OBJECT_PATH,
            interface_name=SNI_IFACE,
            signal_name=signal,
            parameters=parameters,
        )

    def _method_call(self, *args: Any) -> None:
        method, invocation = args[4], args[6]
        callback = self._callbacks.get(method)
        if callback is not None:
            GLib.idle_add(self._run, callback)
        invocation.return_value(None)

    @staticmethod
    def _run(callback: Callable[[], None]) -> bool:
        try:
            callback()
        except Exception:
            LOGGER.exception("Tray callback failed")
        return GLib.SOURCE_REMOVE

    def _get_property(self, *args: Any) -> GLib.Variant:
        values: dict[str, GLib.Variant] = {
            "Category": GLib.Variant("s", CATEGORY),
            "Id": GLib.Variant("s", ITEM_ID),
            "Title": GLib.Variant("s", self._title),
            "Status": GLib.Variant("s", self._status),
            "IconName": GLib.Variant("s", self._icon_name),
            "IconThemePath": GLib.Variant("s", self._theme_path),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], self._tooltip, "")),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_OBJECT_PATH),
            "XAyatanaLabel": GLib.Variant("s", self._label),
            "XAyatanaLabelGuide": GLib.Variant("s", self._guide),
        }
        return values[args[4]]
