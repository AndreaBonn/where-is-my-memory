import threading
from dataclasses import dataclass, field

from tests.core.disk_helpers import cache, report
from tests.core.planning_helpers import group, proc, snapshot
from tests.service.app_service_actions_helpers import OWNER_UID, FakeExecutor
from tests.service.service_helpers import (
    TIMEOUT_S,
    FakeSampler,
    spin_until,
)
from wimm.config import Config
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import Category
from wimm.service.actions import ActionSetup
from wimm.service.app_service import AppService

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
