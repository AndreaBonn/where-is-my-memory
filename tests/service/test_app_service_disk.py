import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from gi.repository import GLib

from tests.core.disk_helpers import MB, cache, docker_disk, image, report
from tests.core.planning_helpers import group, proc, snapshot
from tests.service.service_helpers import (
    TIMEOUT_S,
    FakeSampler,
    spin_for,
    spin_until,
)
from tests.service.test_app_service_actions import OWNER_UID, FakeExecutor
from tests.service.test_sampler import make_sampler
from wimm.config import Config
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, Category, TargetId
from wimm.paths import UserPaths
from wimm.service.actions import ActionSetup
from wimm.service.app_service import AppService
from wimm.service.errors import TargetChanged

QUICK_START_S = 0.01


@dataclass
class FakeScanner:
    """Blocks inside ``scan`` until released, so tests can observe a running scan."""

    result: DiskReport = field(default_factory=lambda: report(caches=(cache(kind=CacheKind.UV),)))
    fail: bool = False
    gate: threading.Event = field(default_factory=threading.Event)
    entered: threading.Event = field(default_factory=threading.Event)
    threads: list[int] = field(default_factory=list)
    configs: list[Config] = field(default_factory=list)
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def scan(self, *, config: Config) -> DiskReport:
        self.threads.append(threading.get_ident())
        self.configs.append(config)
        self.entered.set()
        assert self.gate.wait(timeout=TIMEOUT_S)
        if self.fail:
            raise OSError("scan failed")
        return self.result


@dataclass
class Rig:
    service: AppService
    sampler: FakeSampler
    scanner: FakeScanner
    updated: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)


def build_rig(*, start_delay_s: float = QUICK_START_S, config: Config | None = None) -> Rig:
    sampler = FakeSampler()
    sampler.proceed.set()
    scanner = FakeScanner()
    service = AppService(sampler=sampler, config=config or Config())
    service.attach_disk_scanner(scanner=scanner, start_delay_s=start_delay_s)
    rig = Rig(service=service, sampler=sampler, scanner=scanner)
    service.connect("disk-report-updated", lambda *_: rig.updated.append(threading.get_ident()))
    service.connect("disk-scan-failed", lambda *_: rig.failed.append(threading.get_ident()))
    return rig


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


def test_a_new_report_hands_the_safe_total_to_the_sampler_worker_and_samples() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    rig.scanner.result = report(
        docker=docker_disk(images=(image(char="a", size=4 * MB),)),
        caches=(cache(kind=CacheKind.UV, size=2 * MB), cache(kind=CacheKind.TRASH, size=9 * MB)),
    )
    try:
        rig.service.start()
        spin_until(predicate=lambda: bool(rig.updated))
        spin_until(predicate=lambda: bool(rig.sampler.reclaimable))
        spin_until(predicate=lambda: rig.sampler.calls >= 2)
        total, thread = rig.sampler.reclaimable[-1]
        assert total == 6 * MB
        assert thread in rig.sampler.cycle_threads
    finally:
        rig.service.stop()


def test_the_sampler_puts_the_applied_total_in_the_next_snapshot(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    assert sampler.run_cycle().reclaimable_now.disk == 0
    sampler.apply_reclaimable_disk(reclaimable_disk=5 * MB)
    assert sampler.run_cycle().reclaimable_now.disk == 5 * MB
    sampler.apply_reclaimable_disk(reclaimable_disk=0)
    assert sampler.run_cycle().reclaimable_now.disk == 0


def test_plan_receives_the_latest_disk_report() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    rig.scanner.result = report(caches=(cache(kind=CacheKind.UV, size=2 * MB),))
    setup = ActionSetup(executor=FakeExecutor(), owner_uid=OWNER_UID, measure_delay_s=0.0)
    service = AppService(sampler=rig.sampler, config=Config(), actions=setup)
    service.attach_disk_scanner(scanner=rig.scanner, start_delay_s=QUICK_START_S)
    request = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("uv"))
    try:
        service.start()
        spin_until(predicate=lambda: service.snapshot() is not None)
        with pytest.raises(Exception, match="Disk report not available"):
            service.plan(request=request)
        service.rescan_disk()
        spin_until(predicate=lambda: service.disk_report() is not None)
        plan = service.plan(request=request)
        assert plan.estimated_reclaim_disk == 2 * MB
    finally:
        service.stop()


def test_without_a_scanner_rescan_does_nothing_and_the_report_stays_empty() -> None:
    service = AppService(sampler=FakeSampler(), config=Config())
    try:
        service.start()
        service.rescan_disk()
        spin_for(seconds=0.05)
        assert service.disk_report() is None
    finally:
        service.stop()


def test_stop_cancels_a_running_scan() -> None:
    rig = build_rig()
    rig.service.rescan_disk()
    assert rig.scanner.entered.wait(timeout=TIMEOUT_S)
    assert rig.scanner.cancelled is False
    rig.service.stop()
    rig.scanner.gate.set()
    assert rig.scanner.cancelled is True


def test_an_interval_change_before_the_first_scan_applies_to_its_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[int] = []
    real_add = GLib.timeout_add_seconds

    def add(interval: int, callback: Callable[[], bool]) -> int:
        scheduled.append(interval)
        return real_add(interval, callback)

    rig = build_rig(start_delay_s=0.2)
    rig.scanner.gate.set()
    paths = UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path / "k")
    try:
        rig.service.start()
        monkeypatch.setattr(GLib, "timeout_add_seconds", add)
        rig.service.update_config(
            changes={"disk_scan_interval_s": 7200}, paths=paths, home=tmp_path
        )
        assert 7200 not in scheduled
        spin_until(predicate=lambda: bool(rig.updated))
        assert 7200 in scheduled
        assert Config().disk_scan_interval_s not in scheduled
    finally:
        monkeypatch.undo()
        rig.service.stop()


def disk_action_service(rig: Rig, executor: FakeExecutor | None = None) -> AppService:
    setup = ActionSetup(
        executor=executor or FakeExecutor(), owner_uid=OWNER_UID, measure_delay_s=0.0
    )
    rig.sampler.current = snapshot(
        group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=8),))
    )
    service = AppService(sampler=rig.sampler, config=Config(), actions=setup)
    service.attach_disk_scanner(scanner=rig.scanner, start_delay_s=QUICK_START_S)
    service.start()
    spin_until(predicate=lambda: service.disk_report() is not None)
    return service


def run_plan(*, service: AppService, request: ActionRequest) -> None:
    finished: list[str] = []
    service.connect("action-finished", lambda _s, plan_id, _o: finished.append(plan_id))
    plan = service.plan(request=request)
    service.execute(plan_id=plan.plan_id, typed_confirmation=plan.confirm_phrase)
    spin_until(predicate=lambda: bool(finished))


def test_a_finished_disk_action_triggers_one_rescan_and_a_process_action_does_not() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    service = disk_action_service(rig)
    try:
        scans = len(rig.scanner.configs)
        terminate = ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId("8"))
        run_plan(service=service, request=terminate)
        spin_for(seconds=0.15)
        assert len(rig.scanner.configs) == scans

        clean = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("uv"))
        run_plan(service=service, request=clean)
        spin_until(predicate=lambda: len(rig.scanner.configs) == scans + 1)
        spin_for(seconds=0.15)
        assert len(rig.scanner.configs) == scans + 1
    finally:
        service.stop()


def test_a_refused_disk_action_does_not_rescan_and_the_next_one_that_runs_does() -> None:
    rig = build_rig()
    rig.scanner.gate.set()
    executor = FakeExecutor(error=TargetChanged())
    service = disk_action_service(rig, executor)
    rejected: list[str] = []
    service.connect("action-rejected", lambda _s, plan_id, _e: rejected.append(plan_id))
    try:
        scans = len(rig.scanner.configs)
        clean = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("uv"))
        refused = service.plan(request=clean)
        service.execute(plan_id=refused.plan_id, typed_confirmation=refused.confirm_phrase)
        spin_until(predicate=lambda: bool(rejected))
        # A rescan is flagged synchronously when requested, before the signal is emitted.
        assert service.disk_scanning() is False
        assert len(rig.scanner.configs) == scans

        executor.error = None
        run_plan(service=service, request=clean)
        spin_until(predicate=lambda: len(rig.scanner.configs) == scans + 1)
    finally:
        service.stop()


def test_a_scan_that_starts_announces_itself_on_the_main_thread() -> None:
    rig = build_rig()
    started: list[int] = []
    rig.service.connect("disk-scan-started", lambda *_: started.append(threading.get_ident()))
    try:
        assert rig.service.disk_scanning() is False
        rig.service.rescan_disk()
        assert started == [threading.get_ident()]
        assert rig.service.disk_scanning() is True
        rig.service.rescan_disk()
        assert len(started) == 1
        rig.scanner.gate.set()
        spin_until(predicate=lambda: len(rig.updated) == 2)
        assert len(started) == 2
        assert rig.service.disk_scanning() is False
    finally:
        rig.scanner.gate.set()
        rig.service.stop()


def test_a_rescan_without_a_scanner_announces_nothing() -> None:
    service = AppService(sampler=FakeSampler(), config=Config())
    started: list[int] = []
    service.connect("disk-scan-started", lambda *_: started.append(1))
    service.rescan_disk()
    assert started == []
    assert service.disk_scanning() is False
    service.stop()
