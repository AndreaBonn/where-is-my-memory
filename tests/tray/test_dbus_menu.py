import pytest
from gi.repository import Gio, GLib

from tests.service.test_app_service import spin_until
from tests.tray.conftest import Bus
from wimm.tray.dbus_menu import (
    DBUSMENU_IFACE,
    DBUSMENU_VERSION,
    DBusMenu,
    MenuItem,
    build_layout,
    item_properties,
    items_hash,
)
from wimm.tray.status_notifier import MENU_OBJECT_PATH

OPEN = MenuItem(id=1, label="Apri", callback_id="open")
SEPARATOR = MenuItem(id=2, kind="separator")
QUIT = MenuItem(id=3, label="Esci", callback_id="quit")
ITEMS = [OPEN, SEPARATOR, QUIT]
INVALID_ID_ERROR = "com.canonical.dbusmenu.Error.InvalidMenuItemId"


def unboxed(variant: GLib.Variant) -> object:
    return variant.unpack()


def test_items_hash_is_equal_for_equal_items_and_differs_on_any_field() -> None:
    assert items_hash(items=ITEMS) == items_hash(items=list(ITEMS))
    changed = [OPEN, SEPARATOR, MenuItem(id=3, label="Esci", enabled=False, callback_id="quit")]
    assert items_hash(items=ITEMS) != items_hash(items=changed)
    assert items_hash(items=ITEMS) != items_hash(items=ITEMS[:2])


def test_item_properties_describe_normal_and_separator_entries() -> None:
    assert unboxed(GLib.Variant("a{sv}", item_properties(item=OPEN))) == {
        "label": "Apri",
        "enabled": True,
    }
    assert unboxed(GLib.Variant("a{sv}", item_properties(item=SEPARATOR))) == {"type": "separator"}


def test_item_properties_escape_underscores_and_filter_by_names() -> None:
    item = MenuItem(id=4, label="a_b", enabled=False)
    assert unboxed(GLib.Variant("a{sv}", item_properties(item=item, names=["label"]))) == {
        "label": "a__b"
    }


def test_build_layout_lists_children_only_when_depth_allows() -> None:
    root_id, root_props, children = build_layout(items=ITEMS, depth=-1, names=[])
    assert (root_id, root_props["children-display"].unpack()) == (0, "submenu")
    assert [child.unpack()[0] for child in children] == [1, 2, 3]
    assert build_layout(items=ITEMS, depth=0, names=[])[2] == []


@pytest.mark.dbus
def test_get_layout_returns_the_items_and_the_revision(bus: Bus) -> None:
    menu = DBusMenu(connection=bus.server, on_click=lambda _callback_id: None)
    try:
        menu.set_items(ITEMS)
        reply = bus.call(
            path=MENU_OBJECT_PATH,
            interface=DBUSMENU_IFACE,
            method="GetLayout",
            parameters=GLib.Variant("(iias)", (0, -1, [])),
        )
        revision, (root_id, _props, children) = reply.unpack()
        assert (revision, root_id) == (1, 0)
        assert [(child[0], child[1]) for child in children] == [
            (1, {"label": "Apri", "enabled": True}),
            (2, {"type": "separator"}),
            (3, {"label": "Esci", "enabled": True}),
        ]
        group = bus.call(
            path=MENU_OBJECT_PATH,
            interface=DBUSMENU_IFACE,
            method="GetGroupProperties",
            parameters=GLib.Variant("(aias)", ([3], ["label"])),
        )
        assert group.unpack() == ([(3, {"label": "Esci"})],)
        version = bus.get(path=MENU_OBJECT_PATH, interface=DBUSMENU_IFACE, name="Version")
        assert version == DBUSMENU_VERSION
    finally:
        menu.close()


@pytest.mark.dbus
def test_clicked_event_invokes_the_callback_of_that_item(bus: Bus) -> None:
    clicked: list[str] = []
    menu = DBusMenu(connection=bus.server, on_click=clicked.append)
    try:
        menu.set_items(ITEMS)
        for item_id, event in ((1, "hovered"), (3, "clicked")):
            bus.call(
                path=MENU_OBJECT_PATH,
                interface=DBUSMENU_IFACE,
                method="Event",
                parameters=GLib.Variant("(isvu)", (item_id, event, GLib.Variant("s", ""), 0)),
            )
        spin_until(predicate=lambda: bool(clicked))
        assert clicked == ["quit"]
    finally:
        menu.close()


@pytest.mark.dbus
def test_set_items_emits_layout_updated_only_when_the_items_change(bus: Bus) -> None:
    updates = bus.subscribe(path=MENU_OBJECT_PATH, interface=DBUSMENU_IFACE, member="LayoutUpdated")
    menu = DBusMenu(connection=bus.server, on_click=lambda _callback_id: None)

    def flush() -> None:
        bus.get(path=MENU_OBJECT_PATH, interface=DBUSMENU_IFACE, name="Version")

    try:
        assert menu.set_items(ITEMS) is True
        assert menu.set_items(list(ITEMS)) is False
        flush()
        assert updates == [(1, 0)]
        assert menu.set_items([OPEN]) is True
        flush()
        assert updates == [(1, 0), (2, 0)]
    finally:
        menu.close()


@pytest.mark.dbus
def test_get_layout_of_an_unknown_parent_id_is_a_dbus_error_not_the_root(bus: Bus) -> None:
    # Reference (libdbusmenu bus_get_layout, libdbusmenu-glib/server.c): a parentId that is not
    # a menu item is answered with an error (INVALID_MENUITEM_ID); only the root is made up.
    menu = DBusMenu(connection=bus.server, on_click=lambda _callback_id: None)
    try:
        menu.set_items(ITEMS)
        with pytest.raises(GLib.Error) as raised:
            bus.call(
                path=MENU_OBJECT_PATH,
                interface=DBUSMENU_IFACE,
                method="GetLayout",
                parameters=GLib.Variant("(iias)", (999, -1, [])),
            )
        assert Gio.DBusError.get_remote_error(raised.value) == INVALID_ID_ERROR
        root = bus.call(
            path=MENU_OBJECT_PATH,
            interface=DBUSMENU_IFACE,
            method="GetLayout",
            parameters=GLib.Variant("(iias)", (0, 0, [])),
        )
        assert root.unpack()[1][0] == 0
    finally:
        menu.close()
