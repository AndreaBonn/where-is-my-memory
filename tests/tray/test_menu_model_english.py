import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.tray.menu_helpers import base_snapshot, make_group, with_groups
from wimm.model.memory import Reclaimable
from wimm.tray import menu_model as mm
from wimm.tray.dbus_menu import MenuItem

pytestmark = pytest.mark.usefixtures("english")
GB = 1_000_000_000


@pytest.fixture
def rome_timezone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Europe/Rome for the test, then the original timezone again for the next one."""
    monkeypatch.setenv("TZ", "Europe/Rome")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def labels(items: list[MenuItem]) -> list[str]:
    return [item.label for item in items if item.kind == "normal"]


def test_label_and_tooltip_read_in_english() -> None:
    snapshot = replace(base_snapshot(), reclaimable_now=Reclaimable(ram=4_200_000_000, disk=0))
    assert mm.tray_label(snapshot=snapshot) == "4.2 GB to free up"
    assert mm.tray_tooltip(snapshot=snapshot) == "Memory used 79%, disk: 28 GB free"


def test_menu_entries_read_in_english() -> None:
    snapshot = with_groups(make_group("big", reclaimable=3 * GB))
    assert labels(mm.build_menu(snapshot=snapshot, consecutive_failures=0)) == [
        "Open Where Is My Memory",
        "Memory used: 79%",
        "Disk: 28 GB free",
        "To free up:",
        "big (3.0 GB)",
        "Mute notifications for 1 h",
        "Quit",
    ]


def test_error_and_muted_entries_read_in_english(rome_timezone: None) -> None:
    until = datetime(2026, 10, 16, 12, 30, tzinfo=UTC)
    items = mm.build_menu(snapshot=None, consecutive_failures=3, muted_until=until)
    assert labels(items) == [
        "Monitoring failed: open the panel for details",
        "Notifications muted until 14:30",
        "Quit",
    ]
