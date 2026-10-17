from pathlib import Path
from typing import Any

import pytest
from gi.repository import Gio, GLib

from tests.service.test_app_service import spin_until
from tests.tray.conftest import Bus
from wimm.tray.status_notifier import (
    CATEGORY,
    ICON_NORMAL,
    INSTALLED_ICON_DIRECTORY,
    ITEM_ID,
    LABEL_GUIDE,
    SNI_IFACE,
    SNI_OBJECT_PATH,
    WATCHER_NAME,
    WATCHER_PATH,
    StatusNotifierItem,
    icon_theme_path,
)

WATCHER_XML = """
<node><interface name="org.kde.StatusNotifierWatcher">
  <method name="RegisterStatusNotifierItem">
    <arg type="s" name="service" direction="in"/>
  </method>
</interface></node>
"""


def make_item(bus: Bus, calls: list[str]) -> StatusNotifierItem:
    return StatusNotifierItem(
        connection=bus.server,
        on_activate=lambda: calls.append("activate"),
        on_secondary_activate=lambda: calls.append("secondary"),
        title="Where Is My Memory",
    )


def get(bus: Bus, name: str) -> object:
    return bus.get(path=SNI_OBJECT_PATH, interface=SNI_IFACE, name=name)


def test_icon_theme_path_points_at_source_tree_icons_in_development() -> None:
    path = Path(icon_theme_path())
    assert path.name == "icons"
    assert (path / "hicolor" / "scalable" / "status" / "wimm-normal.svg").is_file()
    assert path != INSTALLED_ICON_DIRECTORY


@pytest.mark.dbus
def test_static_properties_follow_the_specification(bus: Bus) -> None:
    item = make_item(bus, [])
    try:
        assert get(bus, "ItemIsMenu") is False
        assert get(bus, "Category") == CATEGORY == "SystemServices"
        assert get(bus, "Id") == ITEM_ID == "io.github.wimm.WhereIsMyMemory"
        assert get(bus, "XAyatanaLabelGuide") == LABEL_GUIDE == "88,8 GB da liberare"
        assert get(bus, "IconName") == ICON_NORMAL
        assert get(bus, "Menu") == "/MenuBar"
        assert get(bus, "IconThemePath") == icon_theme_path()
    finally:
        item.close()


@pytest.mark.dbus
def test_dynamic_properties_reflect_setters(bus: Bus) -> None:
    item = make_item(bus, [])
    try:
        item.label, item.tooltip, item.status = "9,1 GB", "RAM 30,1/38,9 GB", "NeedsAttention"
        assert get(bus, "XAyatanaLabel") == "9,1 GB"
        assert get(bus, "Status") == "NeedsAttention"
        assert get(bus, "ToolTip") == ("", [], "RAM 30,1/38,9 GB", "")
    finally:
        item.close()


@pytest.mark.dbus
def test_activate_and_secondary_activate_call_their_callbacks(bus: Bus) -> None:
    calls: list[str] = []
    item = make_item(bus, calls)
    try:
        for method in ("Activate", "SecondaryActivate"):
            bus.call(
                path=SNI_OBJECT_PATH,
                interface=SNI_IFACE,
                method=method,
                parameters=GLib.Variant("(ii)", (0, 0)),
            )
        spin_until(predicate=lambda: len(calls) == 2)
        assert calls == ["activate", "secondary"]
    finally:
        item.close()


@pytest.mark.dbus
def test_changing_the_icon_emits_new_icon_once_and_same_value_nothing(bus: Bus) -> None:
    new_icon = bus.subscribe(path=SNI_OBJECT_PATH, interface=SNI_IFACE, member="NewIcon")
    item = make_item(bus, [])
    try:
        item.icon_name = "wimm-warning"
        item.icon_name = "wimm-warning"
        assert get(bus, "IconName") == "wimm-warning"
        assert new_icon == [()]
        item.icon_name = "wimm-critical"
        assert get(bus, "IconName") == "wimm-critical"
        assert len(new_icon) == 2
    finally:
        item.close()


@pytest.mark.dbus
def test_status_tooltip_and_label_setters_emit_their_signals_only_on_change(bus: Bus) -> None:
    kwargs = {"path": SNI_OBJECT_PATH, "interface": SNI_IFACE}
    status = bus.subscribe(member="NewStatus", **kwargs)
    tooltip = bus.subscribe(member="NewToolTip", **kwargs)
    label = bus.subscribe(member="XAyatanaNewLabel", **kwargs)
    item = make_item(bus, [])
    try:
        for _ in range(2):
            item.status = "Passive"
            item.tooltip = "RAM 1/2 GB"
            item.label = "9 GB"
        get(bus, "Status")
        assert status == [("Passive",)]
        assert tooltip == [()]
        assert label == [("9 GB", LABEL_GUIDE)]
    finally:
        item.close()


@pytest.mark.dbus
def test_register_with_watcher_sends_the_unique_name(bus: Bus) -> None:
    received: list[str] = []

    def watcher_call(*args: Any) -> None:
        received.append(args[5].unpack()[0])
        args[6].return_value(None)

    info = Gio.DBusNodeInfo.new_for_xml(xml_data=WATCHER_XML)
    bus.client.register_object(
        object_path=WATCHER_PATH,
        interface_info=info.interfaces[0],
        method_call_closure=watcher_call,
        get_property_closure=None,
        set_property_closure=None,
    )
    owned = bus.client.call_sync(
        bus_name="org.freedesktop.DBus",
        object_path="/org/freedesktop/DBus",
        interface_name="org.freedesktop.DBus",
        method_name="RequestName",
        parameters=GLib.Variant("(su)", (WATCHER_NAME, 0)),
        reply_type=None,
        flags=Gio.DBusCallFlags.NONE,
        timeout_msec=3000,
        cancellable=None,
    )
    assert owned.unpack() == (1,)
    item = make_item(bus, [])
    try:
        item.register_with_watcher()
        spin_until(predicate=lambda: bool(received))
        assert received == [bus.server.get_unique_name()]
    finally:
        item.close()
