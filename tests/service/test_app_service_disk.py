import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from gi.repository import GLib

from tests.service.app_service_disk_helpers import (
    build_rig,
)
from tests.service.service_helpers import (
    TIMEOUT_S,
    spin_for,
    spin_until,
)
from wimm.config import Config
from wimm.paths import UserPaths

FAKE_SOURCE_BASE = 10_000_000


class Timers:
    """Records the timers the disk side arms, so a test fires them instead of waiting."""

    def __init__(self) -> None:
        self.delayed: list[tuple[int, int, Callable[[], bool]]] = []  # (id, delay_ms, callback)
        self.seconds: list[tuple[int, Callable[[], bool]]] = []  # (interval_s, callback)
        self.removed: list[int] = []

    def arm_delayed(self, delay_ms: int, callback: Callable[[], bool]) -> int:
        source_id = FAKE_SOURCE_BASE + len(self.delayed)
        self.delayed.append((source_id, delay_ms, callback))
        return source_id

    def arm_seconds(self, interval: int, callback: Callable[[], bool]) -> int:
        self.seconds.append((interval, callback))
        return FAKE_SOURCE_BASE + 1000 + len(self.seconds)


@pytest.fixture
def timers(monkeypatch: pytest.MonkeyPatch) -> Timers:
    """Capture the start-delay timer instead of running it; record removals."""
    recorded = Timers()
    real_remove = GLib.source_remove

    def remove(source_id: int) -> bool:
        recorded.removed.append(source_id)
        return True if source_id >= FAKE_SOURCE_BASE else real_remove(source_id)

    monkeypatch.setattr(GLib, "timeout_add", recorded.arm_delayed)
    monkeypatch.setattr(GLib, "source_remove", remove)
    return recorded


def test_rescan_disk_emits_the_signal_on_the_main_thread_and_stores_the_report() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    try:
        assert rig.service.disk_report() is None
        rig.service.rescan_disk()
        spin_until(predicate=lambda: bool(rig.updated))
        assert rig.updated == [threading.get_ident()]
        assert rig.service.disk_report() == rig.scanner.result
        assert rig.failed == []
    finally:
        rig.service.stop()


def test_the_scan_runs_on_its_own_worker_not_the_main_loop_nor_the_sampler() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    try:
        rig.service.start()
        spin_until(predicate=lambda: bool(rig.updated) and bool(rig.sampler.cycle_threads))
        scan_thread = rig.scanner.threads[0]
        assert scan_thread != threading.get_ident()
        assert scan_thread not in rig.sampler.cycle_threads
    finally:
        rig.service.stop()


def test_start_scans_after_the_delay_and_not_before(timers: Timers) -> None:
    rig = build_rig(start_delay_s=60)
    rig.scanner.gate.set()
    try:
        rig.service.start()
        assert [delay_ms for _, delay_ms, _ in timers.delayed] == [60_000]
        assert rig.scanner.threads == []

        assert timers.delayed[0][2]() is GLib.SOURCE_REMOVE  # the delay elapses

        spin_until(predicate=lambda: bool(rig.updated))
        assert len(rig.scanner.threads) == 1
    finally:
        rig.service.stop()


def test_start_twice_arms_one_start_timer_and_start_after_stop_arms_none(timers: Timers) -> None:
    rig = build_rig(start_delay_s=60)
    rig.service.start()
    rig.service.start()
    assert len(timers.delayed) == 1

    rig.service.stop()
    rig.service.start()
    assert len(timers.delayed) == 1


def test_the_disk_timer_tick_rescans_and_stays_scheduled(
    timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = build_rig(start_delay_s=60)
    rig.scanner.gate.set()
    try:
        rig.service.start()
        monkeypatch.setattr(GLib, "timeout_add_seconds", timers.arm_seconds)
        timers.delayed[0][2]()
        spin_until(predicate=lambda: len(rig.updated) == 1)
        assert [interval for interval, _ in timers.seconds] == [21600]

        assert timers.seconds[0][1]() is GLib.SOURCE_CONTINUE

        spin_until(predicate=lambda: len(rig.updated) == 2)
        assert len(rig.scanner.threads) == 2
    finally:
        rig.service.stop()


def test_failure_keeps_the_previous_report_and_emits_disk_scan_failed() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    try:
        rig.service.rescan_disk()
        spin_until(predicate=lambda: bool(rig.updated))
        first = rig.service.disk_report()
        rig.scanner.fail = True
        rig.service.rescan_disk()
        spin_until(predicate=lambda: bool(rig.failed))
        assert rig.failed == [threading.get_ident()]
        assert rig.service.disk_report() is first
        assert len(rig.updated) == 1
        rig.scanner.fail = False
        rig.service.rescan_disk()
        spin_until(predicate=lambda: len(rig.updated) == 2)
    finally:
        rig.service.stop()


def test_requests_during_a_running_scan_coalesce_into_one_rerun() -> None:
    rig = build_rig()
    try:
        rig.service.rescan_disk()
        assert rig.scanner.entered.wait(timeout=TIMEOUT_S)
        for _ in range(5):
            rig.service.rescan_disk()
        assert len(rig.scanner.threads) == 1
        rig.scanner.gate.set()
        spin_until(predicate=lambda: len(rig.updated) == 2)
        spin_for(seconds=0.1)
        assert len(rig.scanner.threads) == 2
        assert len(rig.updated) == 2
    finally:
        rig.scanner.gate.set()
        rig.service.stop()


def test_stop_during_a_scan_discards_its_result() -> None:
    rig = build_rig()
    rig.service.rescan_disk()
    rig.scanner.gate.set()
    spin_until(predicate=lambda: len(rig.updated) == 1)  # a scan that finishes delivers
    delivered = rig.service.disk_report()
    assert delivered == rig.scanner.result

    rig.scanner.gate.clear()
    rig.scanner.entered.clear()
    rig.service.rescan_disk()
    assert rig.scanner.entered.wait(timeout=TIMEOUT_S)
    rig.service.stop()
    rig.scanner.gate.set()
    spin_until(predicate=lambda: not rig.service.disk_scanning())  # the worker has finished

    assert len(rig.updated) == 1
    assert rig.service.disk_report() is delivered
    rig.service.rescan_disk()
    assert len(rig.scanner.threads) == 2


def test_stop_cancels_the_pending_start_timer(timers: Timers) -> None:
    stopped = build_rig(start_delay_s=60)
    kept = build_rig(start_delay_s=60)
    stopped.service.start()
    kept.service.start()
    stopped_id, kept_id = timers.delayed[0][0], timers.delayed[1][0]

    stopped.service.stop()

    assert stopped_id in timers.removed
    assert kept_id not in timers.removed
    kept.scanner.gate.set()
    timers.delayed[1][2]()  # the timer that was not cancelled still fires and scans
    spin_until(predicate=lambda: bool(kept.updated))
    assert stopped.scanner.threads == [] and len(kept.scanner.threads) == 1
    kept.service.stop()


def test_the_scan_reads_the_config_current_at_its_start(tmp_path: Path) -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    paths = UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path / "k")
    try:
        rig.service.rescan_disk()
        spin_until(predicate=lambda: bool(rig.updated))
        rig.service.update_config(changes={"devdirs_min_age_days": 200}, paths=paths, home=tmp_path)
        rig.service.rescan_disk()
        spin_until(predicate=lambda: len(rig.updated) == 2)
        ages = [config.devdirs_min_age_days for config in rig.scanner.configs]
        assert ages == [Config().devdirs_min_age_days, 200]
    finally:
        rig.service.stop()


def test_an_interval_change_reschedules_the_running_disk_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[int] = []
    removed: list[int] = []

    real_add, real_remove = GLib.timeout_add_seconds, GLib.source_remove

    def add(interval: int, callback: Callable[[], bool]) -> int:
        scheduled.append(interval)
        return real_add(interval, callback)

    def remove(source: int) -> bool:
        removed.append(source)
        return real_remove(source)

    rig = build_rig()
    rig.scanner.gate.set()
    paths = UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path / "k")
    try:
        rig.service.start()
        spin_until(predicate=lambda: bool(rig.updated))
        monkeypatch.setattr(GLib, "timeout_add_seconds", add)
        monkeypatch.setattr(GLib, "source_remove", remove)
        rig.service.update_config(
            changes={"disk_scan_interval_s": 7200}, paths=paths, home=tmp_path
        )
        assert 7200 in scheduled
        assert len(removed) == 1
    finally:
        monkeypatch.undo()
        rig.service.stop()
