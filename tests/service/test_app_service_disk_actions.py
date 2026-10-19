import threading

from tests.service.app_service_actions_helpers import FakeExecutor
from tests.service.app_service_disk_helpers import (
    build_rig,
    disk_action_service,
    run_plan,
)
from tests.service.service_helpers import (
    FakeSampler,
    spin_for,
    spin_until,
)
from wimm.config import Config
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.service.app_service import AppService
from wimm.service.errors import TargetChanged


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
