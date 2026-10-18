import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from wimm.tray.status_notifier import MENU_OBJECT_PATH

DBUSMENU_IFACE = "com.canonical.dbusmenu"
DBUSMENU_VERSION = 3
ROOT_ID = 0
RECURSE_ALL = -1
EVENT_CLICKED = "clicked"
# libdbusmenu answers GetLayout for a missing id with its INVALID_MENUITEM_ID error.
INVALID_ID_ERROR = "com.canonical.dbusmenu.Error.InvalidMenuItemId"
LOGGER = logging.getLogger(__name__)

INTROSPECTION = """
<node>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <property name="Version" type="u" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
  </interface>
</node>
"""

Properties = dict[str, GLib.Variant]
Node = tuple[int, Properties, list[GLib.Variant]]


@dataclass(frozen=True)
class MenuItem:
    """One menu entry; callback_id is handed back to the app when it is clicked."""

    id: int
    label: str = ""
    enabled: bool = True
    kind: Literal["normal", "separator"] = "normal"
    callback_id: str = ""


def items_hash(*, items: Sequence[MenuItem]) -> int:
    """Identify the content of a menu so unchanged menus are not republished."""
    return hash(tuple(items))


def item_properties(*, item: MenuItem, names: Sequence[str] = ()) -> Properties:
    """The dbusmenu properties of an item, restricted to ``names`` when given."""
    if item.kind == "separator":
        props = {"type": GLib.Variant("s", "separator")}
    else:
        # A single underscore marks a mnemonic in dbusmenu labels, so it is doubled.
        label = item.label.replace("_", "__")
        props = {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", item.enabled)}
    return {key: value for key, value in props.items() if not names or key in names}


def root_properties() -> Properties:
    return {"children-display": GLib.Variant("s", "submenu")}


def build_layout(*, items: Sequence[MenuItem], depth: int, names: Sequence[str]) -> Node:
    """The root node ``(ia{sv}av)`` with its children; ``av`` entries must be boxed."""
    children = []
    if depth != 0:
        for item in items:
            node: Node = (item.id, item_properties(item=item, names=names), [])
            children.append(GLib.Variant("(ia{sv}av)", node))
    return (ROOT_ID, root_properties(), children)


class UnknownMenuItemError(LookupError):
    """A call named a menu item id that is not in the current layout."""


class DBusMenu:
    """Serve a flat list of MenuItem on com.canonical.dbusmenu at /MenuBar."""

    def __init__(self, *, connection: Gio.DBusConnection, on_click: Callable[[str], None]) -> None:
        self._connection, self._on_click = connection, on_click
        self._items: tuple[MenuItem, ...] = ()
        self._digest = items_hash(items=self._items)
        self._revision = 0
        info = Gio.DBusNodeInfo.new_for_xml(xml_data=INTROSPECTION)
        self._registration = connection.register_object(
            object_path=MENU_OBJECT_PATH,
            interface_info=info.interfaces[0],
            method_call_closure=self._method_call,
            get_property_closure=self._get_property,
            set_property_closure=None,
        )

    def set_items(self, items: Sequence[MenuItem]) -> bool:
        """Replace the entries; returns whether anything was published."""
        digest = items_hash(items=items)
        if digest == self._digest:
            return False
        self._items, self._digest = tuple(items), digest
        self._revision += 1
        self._emit(signal="LayoutUpdated", parameters=GLib.Variant("(ui)", (self._revision, 0)))
        # Many hosts refresh labels from ItemsPropertiesUpdated, not from a re-fetched layout.
        entries = [(item.id, item_properties(item=item)) for item in self._items]
        self._emit(
            signal="ItemsPropertiesUpdated",
            parameters=GLib.Variant("(a(ia{sv})a(ias))", (entries, [])),
        )
        return True

    def close(self) -> None:
        if self._registration:
            self._connection.unregister_object(registration_id=self._registration)
            self._registration = 0

    def _emit(self, *, signal: str, parameters: GLib.Variant) -> None:
        if not self._registration:
            return
        self._connection.emit_signal(
            destination_bus_name=None,
            object_path=MENU_OBJECT_PATH,
            interface_name=DBUSMENU_IFACE,
            signal_name=signal,
            parameters=parameters,
        )

    def _method_call(self, *args: Any) -> None:
        method, params, invocation = args[4], args[5], args[6]
        handlers: dict[str, Callable[..., GLib.Variant | None]] = {
            "GetLayout": self._get_layout,
            "GetGroupProperties": self._get_group_properties,
            "Event": self._event,
            "AboutToShow": lambda _item_id: GLib.Variant("(b)", (False,)),
        }
        handler = handlers.get(method)
        if handler is None:
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD, method
            )
            return
        try:
            reply = handler(*params.unpack())
        except UnknownMenuItemError as error:
            invocation.return_dbus_error(INVALID_ID_ERROR, str(error))
            return
        except Exception as error:
            # Answer anyway: an unanswered call leaves the shell waiting for the D-Bus timeout.
            LOGGER.exception("dbusmenu %s failed", method)
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.FAILED, str(error)
            )
            return
        invocation.return_value(reply)

    def _get_layout(self, parent_id: int, depth: int, names: list[str]) -> GLib.Variant:
        if parent_id == ROOT_ID:
            layout = build_layout(items=self._items, depth=depth, names=names)
        else:
            item = next((item for item in self._items if item.id == parent_id), None)
            if item is None:
                raise UnknownMenuItemError(f"The ID supplied {parent_id} is not a menu item")
            layout = (item.id, item_properties(item=item, names=names), [])
        return GLib.Variant("(u(ia{sv}av))", (self._revision, layout))

    def _get_group_properties(self, ids: list[int], names: list[str]) -> GLib.Variant:
        wanted = [item for item in self._items if not ids or item.id in ids]
        entries = [(item.id, item_properties(item=item, names=names)) for item in wanted]
        if not ids or ROOT_ID in ids:
            entries.insert(0, (ROOT_ID, root_properties()))
        return GLib.Variant("(a(ia{sv}))", (entries,))

    def _event(self, item_id: int, event_id: str, _data: object, _timestamp: int) -> None:
        if event_id != EVENT_CLICKED:
            return None
        for item in self._items:
            if item.id == item_id and item.enabled and item.callback_id:
                GLib.idle_add(self._dispatch, item.callback_id)
        return None

    def _dispatch(self, callback_id: str) -> bool:
        try:
            self._on_click(callback_id)
        except Exception:
            LOGGER.exception("Menu callback %s failed", callback_id)
        return GLib.SOURCE_REMOVE

    def _get_property(self, *args: Any) -> GLib.Variant:
        values = {
            "Version": GLib.Variant("u", DBUSMENU_VERSION),
            "Status": GLib.Variant("s", "normal"),
            "TextDirection": GLib.Variant("s", "ltr"),
        }
        return values[args[4]]
