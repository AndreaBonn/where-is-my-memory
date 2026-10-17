import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from gi.repository import GLib, GObject

from tests.service.test_app_service import spin_until
from tests.tray.conftest import Bus
from tests.tray.menu_helpers import base_snapshot, make_group, with_groups
from wimm.model.snapshot import Snapshot
from wimm.tray.dbus_menu import DBUSMENU_IFACE
from wimm.tray.menu_model import ICON_NORMAL, ICON_WARNING
from wimm.tray.status_notifier import MENU_OBJECT_PATH, SNI_IFACE, SNI_OBJECT_PATH
from wimm.tray.tray import MUTE_DURATION_S, Tray

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
GB = 1_000_000_000


class FakeService(GObject.Object):
    __gsignals__: ClassVar = {
        "snapshot-updated": (GObject.SignalFlags.RUN_LAST, None, ()),
        "cycle-failed": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: Snapshot | None = None
        self.consecutive_failures = 0
        self.muted_until: datetime | None = None
        self.snooze_all_calls: list[float] = []
        self.broken = False

    @property
    def notifications_muted_until(self) -> datetime | None:
        return self.muted_until

    def snapshot(self) -> Snapshot | None:
        if self.broken:
            raise RuntimeError("boom")
        return self._snapshot

    def snooze_all(self, *, duration_s: float) -> None:
        self.snooze_all_calls.append(duration_s)
        self.muted_until = NOW + timedelta(seconds=duration_s)

    def publish(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot
        self.emit("snapshot-updated")

    def fail(self) -> None:
        self.consecutive_failures += 1
        self.emit("cycle-failed")


class Harness:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.service = FakeService()
        self.opened: list[str | None] = []
        self.quits = 0
        self.tray = Tray(
            connection=bus.server,
            service=self.service,
            on_open=self.opened.append,
            on_quit=self.quit,
        )

    def quit(self) -> None:
        self.quits += 1

    def prop(self, name: str) -> Any:
        return self.bus.get(path=SNI_OBJECT_PATH, interface=SNI_IFACE, name=name)

    def entries(self) -> list[tuple[int, dict[str, object]]]:
        reply = self.bus.call(
            path=MENU_OBJECT_PATH,
            interface=DBUSMENU_IFACE,
            method="GetLayout",
            parameters=GLib.Variant("(iias)", (0, -1, [])),
        )
        children = reply.unpack()[1][2]
        return [(child[0], child[1]) for child in children]

    def labels(self) -> list[object]:
        return [props.get("label") for _, props in self.entries()]

    def click(self, label_prefix: str) -> None:
        item_id = next(i for i, p in self.entries() if str(p.get("label")).startswith(label_prefix))
        self.bus.call(
            path=MENU_OBJECT_PATH,
            interface=DBUSMENU_IFACE,
            method="Event",
            parameters=GLib.Variant("(isvu)", (item_id, "clicked", GLib.Variant("s", ""), 0)),
        )


@pytest.fixture
def harness(bus: Bus) -> Iterator[Harness]:
    result = Harness(bus)
    yield result
    result.tray.close()


@pytest.mark.dbus
def test_tray_before_first_cycle_has_fixed_entries_and_no_label(harness: Harness) -> None:
    assert harness.labels() == ["Apri Where Is My Memory", "Silenzia notifiche per 1 h", "Esci"]
    assert harness.prop("XAyatanaLabel") == ""
    assert harness.prop("IconName") == ICON_NORMAL


@pytest.mark.dbus
def test_snapshot_update_refreshes_label_tooltip_icon_and_menu(harness: Harness) -> None:
    harness.service.publish(base_snapshot())
    assert harness.prop("XAyatanaLabel") == "4,2 GB da liberare"
    assert harness.prop("ToolTip")[2] == "Memoria usata 79%, disco: 28 GB liberi"
    assert harness.prop("IconName") == ICON_WARNING
    assert harness.labels() == [
        "Apri Where Is My Memory",
        "Memoria usata: 79%",
        "Disco: 28 GB liberi",
        "Da liberare:",
        "whitebox (1,1 GB)",
        "Silenzia notifiche per 1 h",
        "Esci",
    ]


@pytest.mark.dbus
def test_three_failed_cycles_show_error_entry_and_warning_icon(harness: Harness) -> None:
    for _ in range(2):
        harness.service.fail()
    assert harness.prop("IconName") == ICON_NORMAL
    harness.service.fail()
    assert harness.prop("IconName") == ICON_WARNING
    assert harness.labels()[0] == "Monitoraggio in errore: apri il pannello per i dettagli"
    harness.service.consecutive_failures = 0
    harness.service.publish(base_snapshot())
    assert "Monitoraggio in errore" not in str(harness.labels())


@pytest.mark.dbus
def test_activate_and_secondary_activate_open_the_panel(harness: Harness) -> None:
    for method in ("Activate", "SecondaryActivate"):
        harness.bus.call(
            path=SNI_OBJECT_PATH,
            interface=SNI_IFACE,
            method=method,
            parameters=GLib.Variant("(ii)", (0, 0)),
        )
    spin_until(predicate=lambda: len(harness.opened) == 2)
    assert harness.opened == [None, None]


@pytest.mark.dbus
def test_clicking_a_group_opens_the_panel_on_that_group(harness: Harness) -> None:
    harness.service.publish(with_groups(make_group("api", reclaimable=2 * GB)))
    harness.click("api")
    spin_until(predicate=lambda: bool(harness.opened))
    assert harness.opened == ["id-api"]
    assert harness.quits == 0


@pytest.mark.dbus
def test_quit_entry_requests_quit_only(harness: Harness) -> None:
    harness.click("Esci")
    spin_until(predicate=lambda: harness.quits == 1)
    assert harness.opened == []
    assert harness.service.snooze_all_calls == []


@pytest.mark.dbus
def test_mute_entry_mutes_for_one_hour_and_menu_shows_the_real_state(harness: Harness) -> None:
    harness.click("Silenzia")
    spin_until(predicate=lambda: bool(harness.service.snooze_all_calls))
    assert harness.service.snooze_all_calls == [MUTE_DURATION_S] and MUTE_DURATION_S == 3600
    spin_until(predicate=lambda: "Silenzia notifiche per 1 h" not in harness.labels())
    assert any(
        str(label).startswith("Notifiche silenziate fino alle") for label in harness.labels()
    )


@pytest.mark.dbus
def test_refresh_failure_is_logged_not_raised(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.service.broken = True
    with caplog.at_level(logging.ERROR):
        harness.service.emit("snapshot-updated")
    assert "Tray refresh failed" in caplog.text


@pytest.mark.dbus
def test_close_stops_following_the_service(bus: Bus, caplog: pytest.LogCaptureFixture) -> None:
    harness = Harness(bus)
    harness.tray.close()
    harness.service.broken = True
    with caplog.at_level(logging.ERROR):
        harness.service.publish(base_snapshot())
        harness.service.fail()
    assert "Tray refresh failed" not in caplog.text
