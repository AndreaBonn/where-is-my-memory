import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.tray.menu_helpers import base_snapshot, make_group, with_groups
from wimm.model.enums import ActivityState, Category, Pressure
from wimm.model.memory import Reclaimable
from wimm.model.snapshot import Snapshot
from wimm.tray import menu_model as mm
from wimm.tray.dbus_menu import MenuItem

GB = 1_000_000_000
MB = 1_000_000


def labels(items: list[MenuItem]) -> list[str]:
    return [item.label for item in items if item.kind == "normal"]


def with_reclaimable(ram: int) -> Snapshot:
    return replace(base_snapshot(), reclaimable_now=Reclaimable(ram=ram, disk=0))


def test_label_shows_reclaimable_ram() -> None:
    assert mm.tray_label(snapshot=with_reclaimable(ram=4_200_000_000)) == "4,2 GB inattivi"


def test_label_is_empty_below_100_mb_and_shown_at_100_mb() -> None:
    assert mm.tray_label(snapshot=with_reclaimable(ram=100 * MB - 1)) == ""
    assert mm.tray_label(snapshot=with_reclaimable(ram=100 * MB)) == "100 MB inattivi"


def test_label_is_empty_without_snapshot() -> None:
    assert mm.tray_label(snapshot=None) == ""


def test_tooltip_summarises_ram_and_disk() -> None:
    assert mm.tray_tooltip(snapshot=base_snapshot()) == "RAM 32,9/41,7 GB, disco 88%"


def test_tooltip_is_empty_without_snapshot() -> None:
    assert mm.tray_tooltip(snapshot=None) == ""


@pytest.mark.parametrize(
    ("pressure", "failures", "icon"),
    [
        (Pressure.OK, 0, mm.ICON_NORMAL),
        (Pressure.WARNING, 0, mm.ICON_WARNING),
        (Pressure.CRITICAL, 0, mm.ICON_CRITICAL),
        (Pressure.OK, 2, mm.ICON_NORMAL),
        (Pressure.OK, 3, mm.ICON_WARNING),
        (Pressure.CRITICAL, 5, mm.ICON_CRITICAL),
    ],
)
def test_icon_follows_pressure_and_errors(pressure: Pressure, failures: int, icon: str) -> None:
    snapshot = replace(base_snapshot(), pressure=pressure)
    assert mm.tray_icon(snapshot=snapshot, consecutive_failures=failures) == icon


def test_icon_without_snapshot_depends_only_on_errors() -> None:
    assert mm.tray_icon(snapshot=None, consecutive_failures=0) == mm.ICON_NORMAL
    assert mm.tray_icon(snapshot=None, consecutive_failures=3) == mm.ICON_WARNING


def test_menu_without_snapshot_has_only_fixed_entries() -> None:
    items = mm.build_menu(snapshot=None, consecutive_failures=0)
    assert labels(items) == ["Silenzia notifiche per 1 h", "Esci"]
    assert [item.callback_id for item in items] == [mm.CALLBACK_MUTE, mm.CALLBACK_QUIT]


def test_menu_lists_summary_groups_by_reclaimable_then_fixed_entries() -> None:
    snapshot = with_groups(
        make_group("small", reclaimable=2 * GB // 10),
        make_group("big", reclaimable=3 * GB),
    )
    items = mm.build_menu(snapshot=snapshot, consecutive_failures=0)
    assert labels(items) == [
        "RAM 32,9/41,7 GB",
        "Disco 88% occupato",
        "big (3,0 GB)",
        "small (200 MB)",
        "Silenzia notifiche per 1 h",
        "Esci",
    ]
    assert not items[0].enabled and not items[1].enabled
    big = next(item for item in items if item.label.startswith("big"))
    assert big.enabled and big.callback_id == "group:id-big"


def test_menu_ids_are_unique_and_positive() -> None:
    items = mm.build_menu(
        snapshot=with_groups(make_group("a", reclaimable=GB)), consecutive_failures=0
    )
    ids = [item.id for item in items]
    assert len(ids) == len(set(ids)) and min(ids) > 0


def test_menu_caps_groups_at_five_largest() -> None:
    groups = [make_group(f"g{n}", reclaimable=(n + 1) * GB) for n in range(7)]
    items = mm.build_menu(snapshot=with_groups(*groups), consecutive_failures=0)
    shown = [item.callback_id for item in items if item.callback_id.startswith(mm.GROUP_PREFIX)]
    assert shown == [f"group:id-g{n}" for n in (6, 5, 4, 3, 2)]


def test_menu_keeps_only_idle_actionable_unignored_groups() -> None:
    snapshot = with_groups(
        make_group("idle", reclaimable=GB),
        make_group("active", reclaimable=GB, state=ActivityState.ACTIVE),
        make_group("unknown", reclaimable=GB, state=ActivityState.UNKNOWN),
        make_group("ignored", reclaimable=GB, ignored=True),
        make_group("system", reclaimable=GB, category=Category.SYSTEM),
    )
    items = mm.build_menu(snapshot=snapshot, consecutive_failures=0)
    assert [i.callback_id for i in items if i.callback_id.startswith("group:")] == ["group:id-idle"]


def test_menu_shows_error_entry_first_from_three_failures() -> None:
    snapshot = base_snapshot()
    quiet = mm.build_menu(snapshot=snapshot, consecutive_failures=2)
    failing = mm.build_menu(snapshot=snapshot, consecutive_failures=3)
    message = "Monitoraggio in errore: apri il pannello per i dettagli"
    assert message not in labels(quiet)
    assert labels(failing)[0] == message
    assert failing[0].enabled and failing[0].callback_id == mm.CALLBACK_OPEN
    assert labels(failing[1:]) == labels(quiet)


def test_error_entry_also_without_snapshot() -> None:
    items = mm.build_menu(snapshot=None, consecutive_failures=3)
    assert labels(items)[0].startswith("Monitoraggio in errore")


def test_muted_menu_replaces_the_mute_entry_with_its_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Rome")
    time.tzset()
    until = datetime(2026, 10, 16, 12, 30, tzinfo=UTC)
    items = mm.build_menu(snapshot=None, consecutive_failures=0, muted_until=until)
    assert labels(items) == ["Notifiche silenziate fino alle 14:30", "Esci"]
    assert not items[0].enabled


def test_parse_group_callback() -> None:
    assert mm.parse_group_callback(callback_id="group:id-big") == "id-big"
    assert mm.parse_group_callback(callback_id="open") is None
    assert mm.parse_group_callback(callback_id="group:") is None


def test_fixed_entries_keep_their_id_when_the_menu_content_changes() -> None:
    # A host may deliver a click on the layout the user saw: "Silenzia" must never
    # take the id "Esci" had a cycle earlier, or a stale click would quit the app.
    def ids_by_callback(items: list[MenuItem]) -> dict[str, int]:
        return {item.callback_id: item.id for item in items if item.callback_id}

    bare = ids_by_callback(mm.build_menu(snapshot=None, consecutive_failures=0))
    full = ids_by_callback(
        mm.build_menu(
            snapshot=with_groups(make_group("a", reclaimable=GB), make_group("b", reclaimable=GB)),
            consecutive_failures=3,
        )
    )
    assert bare["mute"] == full["mute"] and bare["quit"] == full["quit"]
    assert full["open"] not in bare.values()
    group_ids = {value for key, value in full.items() if key.startswith("group:")}
    assert len(group_ids) == 2 and not group_ids & set(bare.values())
