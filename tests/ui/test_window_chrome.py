import pytest
from gi.repository import Gio, Gtk

from tests.ui.conftest import (
    FakeSource,
    RefreshableSource,
    WindowFactory,
    descendants,
    focus_is_in,
    present_and_settle,
    wait_until,
)
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets import icon_only_label

pytestmark = pytest.mark.ui
MAIN_MENU_LABEL = "Menu principale"


def test_every_icon_only_button_has_a_tooltip_and_an_accessible_name(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(RefreshableSource(snapshot=snapshot))
    window.overview.group_widgets["g_3f9a1c"].set_expanded(True)
    present_and_settle(window)

    # Only mapped buttons: libadwaita keeps a hidden back button that is not ours to name.
    buttons = [
        w
        for w in descendants(window)
        if isinstance(w, Gtk.Button | Gtk.MenuButton)
        and w.get_icon_name()
        and not w.get_label()
        and w.get_mapped()
    ]

    assert len(buttons) >= 4  # menu, refresh, two member menus
    for button in buttons:
        assert icon_only_label(button=button) == button.get_tooltip_text(), (
            f"unlabelled icon button {button}"
        )
        assert button.get_tooltip_text()


def test_refresh_button_is_hidden_unless_the_source_can_refresh(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    plain = window_factory(FakeSource(snapshot=snapshot))
    capable = window_factory(RefreshableSource(snapshot=snapshot))

    def refresh_buttons(window: Gtk.Widget) -> list[Gtk.Button]:
        return [
            w
            for w in descendants(window)
            if isinstance(w, Gtk.Button) and w.get_action_name() == "win.refresh"
        ]

    assert [b.get_visible() for b in refresh_buttons(plain)] == [False]
    assert [b.get_visible() for b in refresh_buttons(capable)] == [True]
    assert capable.can_refresh
    assert not plain.can_refresh


def test_refresh_action_asks_the_source_for_a_sample(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    source = RefreshableSource(snapshot=snapshot)
    window = window_factory(source)

    window.activate_action("win.refresh", None)

    assert source.refreshes == 1


def test_refresh_does_nothing_for_a_source_without_request_refresh(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))

    window.refresh()


def test_ctrl_f_target_is_the_search_entry(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    search = window.overview._filters.search
    window.overview.focus_search()
    wait_until(lambda: focus_is_in(window, search), description="focus on search")

    focus = window.get_focus()
    assert focus is not None
    assert focus is window.overview._filters.search or focus.is_ancestor(
        window.overview._filters.search
    )


def menu_item_states(window: Gtk.Widget) -> dict[str, bool]:
    """Sensitivity of each entry of the main menu, by label, after popping it up."""
    (menu_button,) = [
        w
        for w in descendants(window)
        if isinstance(w, Gtk.MenuButton) and icon_only_label(button=w) == MAIN_MENU_LABEL
    ]
    menu_button.popup()
    popover = menu_button.get_popover()
    assert popover is not None
    wait_until(popover.get_mapped, description="menu popover mapped")
    states = {}
    for item in descendants(popover):
        if type(item).__name__ == "GtkModelButton":
            label = next(w for w in descendants(item) if isinstance(w, Gtk.Label))
            states[label.get_label()] = item.get_sensitive()
    menu_button.popdown()
    return states


def test_menu_items_are_disabled_when_the_application_lacks_the_actions(
    window_factory: WindowFactory, snapshot: Snapshot, application: Gio.Application
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    before = menu_item_states(window)
    window.window_actions.add_action(Gio.SimpleAction.new("preferences", None))
    after = menu_item_states(window)

    assert before == {"Preferenze": False, "Silenzia 1 h": False, "Info": True, "Esci": False}
    assert after["Preferenze"] is True
    assert after["Info"] is True
    assert after["Esci"] is False


def test_ctrl_comma_activates_win_preferences(
    window_factory: WindowFactory, snapshot: Snapshot, application: Gio.Application
) -> None:
    opened: list[str] = []
    action = Gio.SimpleAction.new("preferences", None)
    action.connect("activate", lambda *_a: opened.append("preferences"))
    window = window_factory(FakeSource(snapshot=snapshot))
    window.window_actions.add_action(action)
    shortcut = next(
        s
        for c in window.observe_controllers()
        if isinstance(c, Gtk.ShortcutController)
        for s in c
        if s.get_trigger().to_string() == "<Control>comma"
    )

    shortcut.get_action().activate(Gtk.ShortcutActionFlags.EXCLUSIVE, window, None)

    assert opened == ["preferences"]
