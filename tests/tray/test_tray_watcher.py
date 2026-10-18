import pytest

from tests.service.test_app_service import spin_until
from tests.tray.conftest import Bus
from tests.tray.test_tray import FakeService
from tests.tray.test_watcher import SHORT_ABSENCE_MS, FakeWatcher, wait_past_timeout
from wimm.tray import tray as tray_module
from wimm.tray.tray import Tray
from wimm.tray.watcher import TrayWatcher


def build(bus: Bus) -> Tray:
    return Tray(
        connection=bus.server,
        service=FakeService(),
        on_open=lambda _group_id: None,
        on_quit=lambda: None,
    )


@pytest.mark.dbus
def test_start_registers_again_after_the_watcher_comes_back(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    fake.appear()
    tray = build(bus)
    try:
        tray.start()
        spin_until(predicate=lambda: len(fake.registrations) == 1)
        fake.vanish()
        fake.appear()
        spin_until(predicate=lambda: len(fake.registrations) == 2)
        assert fake.registrations == [bus.server.get_unique_name()] * 2
    finally:
        tray.close()


def short_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tray_module,
        "TrayWatcher",
        lambda **kwargs: TrayWatcher(**kwargs, absent_after_ms=SHORT_ABSENCE_MS),
    )


@pytest.mark.dbus
def test_the_host_is_present_only_after_a_successful_registration(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    short_absence(monkeypatch)
    fake = FakeWatcher(bus=bus)
    fake.fail = True
    reports: list[bool] = []
    tray = build(bus)
    try:
        tray.start(on_missing=reports.append)
        spin_until(predicate=lambda: reports == [True])
        fake.appear()
        spin_until(predicate=lambda: len(fake.registrations) == 1)
        wait_past_timeout()
        assert reports == [True]  # the registration was refused: the icon is still missing
        fake.fail = False
        fake.vanish()
        fake.appear()
        spin_until(predicate=lambda: reports == [True, False])  # positive pair
    finally:
        tray.close()


@pytest.mark.dbus
def test_presence_is_reported_once_across_repeated_reappearances(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    short_absence(monkeypatch)
    fake = FakeWatcher(bus=bus)
    reports: list[bool] = []
    tray = build(bus)
    try:
        tray.start(on_missing=reports.append)
        spin_until(predicate=lambda: reports == [True])
        fake.appear()
        spin_until(predicate=lambda: reports == [True, False])
        fake.vanish()
        fake.appear()
        spin_until(predicate=lambda: len(fake.registrations) == 2)
        wait_past_timeout()
        assert reports == [True, False]
    finally:
        tray.close()


@pytest.mark.dbus
def test_a_second_start_does_not_create_a_second_watcher(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    fake.appear()
    tray = build(bus)
    try:
        tray.start()
        tray.start()
        spin_until(predicate=lambda: len(fake.registrations) >= 1)
        wait_past_timeout()
        assert len(fake.registrations) == 1
    finally:
        tray.close()


@pytest.mark.dbus
def test_close_stops_following_the_watcher(bus: Bus) -> None:
    fake = FakeWatcher(bus=bus)
    fake.appear()
    tray = build(bus)
    tray.start()
    spin_until(predicate=lambda: len(fake.registrations) == 1)  # followed before close
    fake.vanish()
    tray.close()
    fake.appear()
    wait_past_timeout()
    assert len(fake.registrations) == 1
