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
from wimm.model.snapshot import Group, Snapshot
from wimm.ui.widgets.group_controls import IGNORE_BUTTON_NAME, SNOOZE_BUTTON_PREFIX
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui
GB = 1_000_000_000
GROUP = GroupId("srv")


def one_group(*, ignored: bool = False, snoozed_until: datetime | None = None) -> Snapshot:
    server = actionable(group(gid="srv", name="whitebox", members=(proc(pid=1, reclaimable=GB),)))
    return snapshot(replace(server, ignored=ignored, snoozed_until=snoozed_until))


def actionable(found: Group) -> Group:
    """As assembly does: a group whose members can be stopped offers a stop itself."""
    return replace(found, primary_action=found.members[0].actions[0])


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


def snooze_buttons(window: MainWindow) -> dict[str, Gtk.Button]:
    found = [
        w
        for w in descendants(window)
        if isinstance(w, Gtk.Button) and w.get_name().startswith(SNOOZE_BUTTON_PREFIX)
    ]
    return {button.get_label() or "": button for button in found}


def test_controls_say_what_they_do_in_plain_words(window_factory: WindowFactory) -> None:
    window = window_factory(FakeActionService(snapshot=one_group()))
    open_group(window)

    assert list(snooze_buttons(window)) == ["1 ora", "1 giorno", "7 giorni"]
    texts = [w.get_label() for w in descendants(window) if isinstance(w, Gtk.Label)]
    assert "Non avvisarmi per questo" in texts
    assert "Resta in lista, smetti solo di ricevere avvisi" in texts


def test_snooze_one_day_calls_the_service_with_the_group_and_86400(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)

    snooze_buttons(window)["1 giorno"].emit("clicked")

    assert service.snoozed == [(GROUP, 86400)]


def test_snooze_durations_are_one_hour_one_day_seven_days(window_factory: WindowFactory) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)

    for label in ("1 ora", "7 giorni"):
        snooze_buttons(window)[label].emit("clicked")

    assert service.snoozed == [(GROUP, 3600), (GROUP, 604800)]


def test_ignore_calls_set_ignored_true_and_an_ignored_snapshot_offers_to_undo(
    window_factory: WindowFactory,
) -> None:
    service = FakeActionService(snapshot=one_group())
    window = window_factory(service)
    open_group(window)
    button = named(window, IGNORE_BUTTON_NAME)
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Mai più"

    button.emit("clicked")
    assert service.ignored == [(GROUP, True)]
    service.publish(one_group(ignored=True))
    present_and_settle(window)

    button = named(window, IGNORE_BUTTON_NAME)
    assert isinstance(button, Gtk.Button)
    assert button.get_label() == "Riattiva gli avvisi"
    assert not any(b.get_visible() for b in snooze_buttons(window).values())
    button.emit("clicked")
    assert service.ignored[-1] == (GROUP, False)


def test_the_row_shows_ignored_and_snoozed_state_from_the_snapshot(
    window_factory: WindowFactory, now: datetime
) -> None:
    service = FakeActionService(snapshot=one_group(snoozed_until=now + timedelta(hours=1)))
    window = window_factory(service)
    present_and_settle(window)
    widget = window.overview.group_widgets["srv"]
    assert f"avvisi in pausa fino alle {(now + timedelta(hours=1)):%H:%M}" in widget.get_subtitle()
    assert "senza avvisi" not in widget.get_subtitle()

    service.publish(one_group(ignored=True, snoozed_until=now - timedelta(hours=1)))
    present_and_settle(window)

    assert "senza avvisi" in widget.get_subtitle()
    assert "avvisi in pausa" not in widget.get_subtitle()


def test_controls_are_disabled_with_a_source_without_the_service_methods(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)
    group_id = next(iter(window.overview.group_widgets))
    assert window.overview.expand_group(group_id=group_id)

    assert len(snooze_buttons(window)) == 3
    assert not any(b.get_sensitive() for b in snooze_buttons(window).values())
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
    service.publish(snapshot(actionable(group(gid="srv", name="whitebox", members=members))))
    present_and_settle(window)

    assert named(window, IGNORE_BUTTON_NAME) is before
    assert len(window.overview.group_widgets["srv"]._entries) == 2  # members did change
