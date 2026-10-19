import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from tests.core.planning_helpers import NOW, group, proc, snapshot
from tests.service.service_helpers import (
    TIMEOUT_S,
    FakeSampler,
    FixedClock,
    spin_until,
)
from wimm.config import Config
from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, Category, TargetId
from wimm.model.snapshot import Snapshot
from wimm.service.actions import ActionSetup, ReclaimDelta
from wimm.service.app_service import AppService
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.errors import (
    WimmError,
)

OWNER_UID = 1000
PID = 8


@dataclass
class FakeExecutor:
    error: WimmError | None = None
    gate: threading.Event = field(default_factory=lambda: _open_gate())
    started: threading.Event = field(default_factory=threading.Event)
    plans: list[Plan] = field(default_factory=list)
    threads: list[int] = field(default_factory=list)

    def apply_config(self, *, config: Config) -> None:
        return None

    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        self.started.set()
        self.threads.append(threading.get_ident())
        assert self.gate.wait(timeout=TIMEOUT_S)
        if self.error is not None:
            raise self.error
        self.plans.append(plan)
        return tuple(StepOutcome(order=s.order, status=StepStatus.DONE) for s in plan.steps)


def _open_gate() -> threading.Event:
    gate = threading.Event()
    gate.set()
    return gate


@dataclass
class Rig:
    service: AppService
    sampler: FakeSampler
    executor: FakeExecutor
    clock: FixedClock
    finished: list[tuple[str, tuple[StepOutcome, ...], int]] = field(default_factory=list)
    rejected: list[tuple[str, WimmError]] = field(default_factory=list)
    measured: list[tuple[str, ReclaimDelta]] = field(default_factory=list)


def build_rig(*, base: Snapshot | None = None, executor: FakeExecutor | None = None) -> Rig:
    sampler = FakeSampler()
    sampler.proceed.set()
    sampler.current = base or snapshot(
        group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),))
    )
    clock = FixedClock(NOW)
    fake = executor or FakeExecutor()
    setup = ActionSetup(executor=fake, owner_uid=OWNER_UID, measure_delay_s=0.0)
    service = AppService(sampler=sampler, config=Config(), clock=clock, actions=setup)
    rig = Rig(service=service, sampler=sampler, executor=fake, clock=clock)
    service.connect(
        "action-finished",
        lambda _s, pid, out: rig.finished.append((pid, out, threading.get_ident())),
    )
    service.connect("action-rejected", lambda _s, pid, err: rig.rejected.append((pid, err)))
    service.connect("reclaim-measured", lambda _s, pid, delta: rig.measured.append((pid, delta)))
    service.start()
    spin_until(predicate=lambda: service.snapshot() is not None)
    return rig


def terminate(pid: int = PID) -> ActionRequest:
    return ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId(str(pid)))


def volume(name: str) -> ActionRequest:
    return ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId(name))


class RigFactory:
    def __init__(self) -> None:
        self.rigs: list[Rig] = []

    def build(self, *, base: Snapshot | None = None, executor: FakeExecutor | None = None) -> Rig:
        rig = build_rig(base=base, executor=executor)
        self.rigs.append(rig)
        return rig


@pytest.fixture
def rigs() -> Iterator[RigFactory]:
    factory = RigFactory()
    yield factory
    for rig in factory.rigs:
        rig.sampler.proceed.set()
        rig.executor.gate.set()
        rig.service.stop()
