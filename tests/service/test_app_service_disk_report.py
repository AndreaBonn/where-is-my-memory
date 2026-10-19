from collections.abc import Callable
from pathlib import Path

import pytest
from gi.repository import GLib

from tests.core.disk_helpers import MB, cache, docker_disk, image, report
from tests.service.app_service_actions_helpers import OWNER_UID, FakeExecutor
from tests.service.app_service_disk_helpers import (
    QUICK_START_S,
    build_rig,
)
from tests.service.service_helpers import (
    TIMEOUT_S,
    FakeSampler,
    spin_for,
    spin_until,
)
from tests.service.test_sampler import make_sampler
from wimm.config import Config
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, TargetId
from wimm.paths import UserPaths
from wimm.service.actions import ActionSetup
from wimm.service.app_service import AppService


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
