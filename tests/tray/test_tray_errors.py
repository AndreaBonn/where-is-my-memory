import logging
from typing import Any

import pytest
from gi.repository import GLib

from tests.service.test_app_service import spin_until
from tests.tray.conftest import Bus
from wimm.tray.dbus_menu import DBUSMENU_IFACE, ROOT_ID, DBusMenu, MenuItem
from wimm.tray.status_notifier import (
    MENU_OBJECT_PATH,
    SNI_IFACE,
    SNI_OBJECT_PATH,
    StatusNotifierItem,
)

OPEN = MenuItem(id=1, label="Apri", callback_id="open")
DISABLED = MenuItem(id=2, label="Spento", enabled=False, callback_id="disabled")


def click(bus: Bus, item_id: int) -> None:
    bus.call(
        path=MENU_OBJECT_PATH,
        interface=DBUSMENU_IFACE,
        method="Event",
        parameters=GLib.Variant("(isvu)", (item_id, "clicked", GLib.Variant("s", ""), 0)),
    )


def failing(*_args: Any) -> None:
    raise RuntimeError("boom")


def drain() -> None:
    context = GLib.MainContext.default()
    while context.iteration(False):
        pass


@pytest.mark.dbus
def test_a_failing_menu_handler_answers_with_an_error_instead_of_hanging(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    menu = DBusMenu(connection=bus.server, on_click=lambda _callback_id: None)
    monkeypatch.setattr(target=menu, name="_get_layout", value=failing)
    try:
        with pytest.raises(GLib.Error, match=r"org\.freedesktop\.DBus\.Error\.Failed"):
            bus.call(
                path=MENU_OBJECT_PATH,
                interface=DBUSMENU_IFACE,
                method="GetLayout",
                parameters=GLib.Variant("(iias)", (0, -1, [])),
            )
    finally:
        menu.close()


@pytest.mark.dbus
def test_a_failing_click_callback_is_logged_and_the_menu_keeps_serving(
    bus: Bus, caplog: pytest.LogCaptureFixture
) -> None:
    menu = DBusMenu(connection=bus.server, on_click=failing)
    menu.set_items([OPEN])
    try:
        with caplog.at_level(level=logging.ERROR):
            click(bus=bus, item_id=OPEN.id)
            spin_until(predicate=lambda: "Menu callback open failed" in caplog.messages)
        click(bus=bus, item_id=OPEN.id)  # still answering after the failure
    finally:
        menu.close()


@pytest.mark.dbus
def test_a_click_on_a_disabled_item_runs_nothing(bus: Bus) -> None:
    clicked: list[str] = []
    menu = DBusMenu(connection=bus.server, on_click=clicked.append)
    menu.set_items([OPEN, DISABLED])
    try:
        click(bus=bus, item_id=DISABLED.id)
        click(bus=bus, item_id=OPEN.id)
        spin_until(predicate=lambda: bool(clicked))
        drain()
        assert clicked == ["open"]
    finally:
        menu.close()


@pytest.mark.dbus
def test_group_properties_include_the_root_when_asked(bus: Bus) -> None:
    menu = DBusMenu(connection=bus.server, on_click=lambda _callback_id: None)
    menu.set_items([OPEN])
    try:
        reply = bus.call(
            path=MENU_OBJECT_PATH,
            interface=DBUSMENU_IFACE,
            method="GetGroupProperties",
            parameters=GLib.Variant("(aias)", ([ROOT_ID, OPEN.id], [])),
        ).unpack()[0]
        assert [entry[0] for entry in reply] == [ROOT_ID, OPEN.id]
        assert reply[0][1] == {"children-display": "submenu"}
    finally:
        menu.close()


@pytest.mark.dbus
def test_a_failing_activate_callback_is_logged(bus: Bus, caplog: pytest.LogCaptureFixture) -> None:
    item = StatusNotifierItem(
        connection=bus.server, on_activate=failing, on_secondary_activate=failing, title="wimm"
    )
    try:
        with caplog.at_level(level=logging.ERROR):
            bus.call(
                path=SNI_OBJECT_PATH,
                interface=SNI_IFACE,
                method="Activate",
                parameters=GLib.Variant("(ii)", (0, 0)),
            )
            spin_until(predicate=lambda: "Tray callback failed" in caplog.messages)
    finally:
        item.close()


@pytest.mark.dbus
def test_closed_objects_emit_nothing(bus: Bus) -> None:
    item = StatusNotifierItem(
        connection=bus.server,
        on_activate=lambda: None,
        on_secondary_activate=lambda: None,
        title="wimm",
    )
    menu = DBusMenu(connection=bus.server, on_click=lambda _callback_id: None)
    icons = bus.subscribe(path=SNI_OBJECT_PATH, interface=SNI_IFACE, member="NewIcon")
    layouts = bus.subscribe(path=MENU_OBJECT_PATH, interface=DBUSMENU_IFACE, member="LayoutUpdated")
    item.close()
    menu.close()
    item.icon_name = "wimm-critical-symbolic"
    menu.set_items([OPEN])
    # Positive pair: a live item on the same bus does emit, so the empty lists can fail.
    live = StatusNotifierItem(
        connection=bus.server,
        on_activate=lambda: None,
        on_secondary_activate=lambda: None,
        title="wimm",
    )
    try:
        live.icon_name = "wimm-warning-symbolic"
        spin_until(predicate=lambda: bool(icons))
        assert icons == [()]
        assert layouts == []
    finally:
        live.close()
