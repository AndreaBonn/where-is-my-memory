from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from gi.repository import Gio, Gtk

from tests.core.planning_helpers import group, proc, snapshot
from tests.ui.conftest import (
    FakeActionService,
    FakeSource,
    WindowFactory,
    descendants,
    present_and_settle,
    wait_until,
)
from wimm.model.enums import GroupId
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets.group_controls import IGNORE_BUTTON_NAME, SNOOZE_BUTTON_NAME
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui
GB = 1_000_000_000
GROUP = GroupId("srv")


def one_group(*, ignored: bool = False, snoozed_until: datetime | None = None) -> Snapshot:
    server = group(gid="srv", name="whitebox", members=(proc(pid=1, reclaimable=GB),))
    return snapshot(replace(server, ignored=ignored, snoozed_until=snoozed_until))


def open_group(window: MainWindow) -> None:
    present_and_settle(window)
    assert window.overview.expand_group(group_id="srv")


def named(window: MainWindow, name: str) -> Gtk.Widget:
    (widget,) = [w for w in descendants(window) if w.get_name() == name]
    return widget


def model_buttons(popover: Gtk.Widget) -> dict[str, Gtk.Widget]:
    result: dict[str, Gtk.Widget] = {}
    for item in descendants(popover):
        if type(item).__name__ == "GtkModelButton":
            label = next(w for w in descendants(item) if isinstance(w, Gtk.Label))
            result[label.get_label()] = item
    return result


def pick_snooze(window: MainWindow, label: str) -> None:
    button = named(window, SNOOZE_BUTTON_NAME)
    assert isinstance(button, Gtk.MenuButton)
    button.popup()
    popover = button.get_popover()
    assert popover is not None
    wait_until(popover.get_mapped, description="snooze popover mapped")
    choices = model_buttons(popover)
    assert list(choices) == ["1 h", "24 h", "7 giorni"]
    choices[label].emit("clicked")


def test_snooze_24h_calls_the_service_with_the_group_and_86400(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)

    pick_snooze(window, "24 h")

    assert service.snoozed == [(GROUP, 86400)]


def test_snooze_durations_are_one_hour_one_day_seven_days(window_factory: WindowFactory) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)

    for label in ("1 h", "7 giorni"):
        pick_snooze(window, label)

    assert service.snoozed == [(GROUP, 3600), (GROUP, 604800)]


def test_ignore_calls_set_ignored_true_and_an_ignored_snapshot_offers_to_undo(
    window_factory: WindowFactory,
) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)
    button = named(window, IGNORE_BUTTON_NAME)
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Ignora"

    button.emit("clicked")
    assert service.ignored == [(GROUP, True)]
    service.publish(one_group(ignored=True))
    present_and_settle(window)

    button = named(window, IGNORE_BUTTON_NAME)
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Non ignorare più"
    button.emit("clicked")
    assert service.ignored[-1] == (GROUP, False)


def test_the_row_shows_ignored_and_snoozed_state_from_the_snapshot(
    window_factory: WindowFactory, now: datetime
) -> None:
    service = FakeActionService(snapshot=one_group(snoozed_until=now + timedelta(hours=1)))
    window = window_factory(service)
    present_and_settle(window)
    widget = window.overview.group_widgets["srv"]
    assert f"silenziato fino alle {(now + timedelta(hours=1)):%H:%M}" in widget.get_subtitle()
    assert "ignorato" not in widget.get_subtitle()

    service.publish(one_group(ignored=True, snoozed_until=now - timedelta(hours=1)))
    present_and_settle(window)

    assert "ignorato" in widget.get_subtitle()
    assert "silenziato" not in widget.get_subtitle()


def test_controls_are_disabled_with_a_source_without_the_service_methods(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)
    group_id = next(iter(window.overview.group_widgets))
    assert window.overview.expand_group(group_id=group_id)

    assert not named(window, SNOOZE_BUTTON_NAME).get_sensitive()
    assert not named(window, IGNORE_BUTTON_NAME).get_sensitive()


def menu_state(window: MainWindow) -> dict[str, bool]:
    button = next(
        w for w in descendants(window) if isinstance(w, Gtk.MenuButton) and w.get_primary()
    )
    button.popup()
    popover = button.get_popover()
    assert popover is not None
    wait_until(popover.get_mapped, description="menu popover mapped")
    states = {label: item.get_sensitive() for label, item in model_buttons(popover).items()}
    items = model_buttons(popover)
    if "Silenzia 1 h" in items:
        items["Silenzia 1 h"].emit("clicked")
    button.popdown()
    return states


def test_window_menu_snoozes_all_for_one_hour_then_shows_the_end_and_disables(
    window_factory: WindowFactory,
) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    present_and_settle(window)

    assert menu_state(window)["Silenzia 1 h"] is True
    assert service.snoozed_all == [3600]
    until = datetime.now().astimezone() + timedelta(hours=1)
    service.notifications_muted_until = until
    service.publish(one_group())
    present_and_settle(window)

    states = menu_state(window)
    assert states[f"Notifiche silenziate fino alle {until:%H:%M}"] is False
    assert "Silenzia 1 h" not in states
    assert service.snoozed_all == [3600]


def test_window_menu_entry_is_disabled_without_snooze_all(
    window_factory: WindowFactory, snapshot: Snapshot, application: Gio.Application
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    assert menu_state(window)["Silenzia 1 h"] is False


def test_controls_survive_a_change_in_the_group_members(window_factory: WindowFactory) -> None:
    # A process starting or ending must not rebuild the controls: an open "Silenzia"
    # menu or the focus on "Ignora" would be lost every time.
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)
    before = named(window, IGNORE_BUTTON_NAME)

    members = (proc(pid=1, reclaimable=GB), proc(pid=2, reclaimable=GB))
    service.publish(snapshot(group(gid="srv", name="whitebox", members=members)))
    present_and_settle(window)

    assert named(window, IGNORE_BUTTON_NAME) is before
    assert len(window.overview.group_widgets["srv"]._entries) == 2  # members did change
