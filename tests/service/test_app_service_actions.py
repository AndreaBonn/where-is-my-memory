import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from time import monotonic

import pytest
from gi.repository import GLib

from tests.core.disk_helpers import docker_disk, report
from tests.core.disk_helpers import volume as disk_volume
from tests.core.planning_helpers import NOW, group, proc, snapshot
from tests.service.service_helpers import (
    TIMEOUT_S,
    FakeSampler,
    FixedClock,
    spin_for,
    spin_until,
    with_free_space,
)
from wimm.config import Config
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind, Category, PlanId, TargetId
from wimm.model.snapshot import Snapshot
from wimm.service.actions import ActionSetup, ReclaimDelta
from wimm.service.app_service import AppService
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.errors import (
    ConfirmationMismatch,
    InvalidRequest,
    PlanExpired,
    PlanNotFound,
    TargetChanged,
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


def test_execute_delivers_outcomes_on_the_main_loop_from_a_worker(rigs: RigFactory) -> None:
    rig = rigs.build()
    plan = rig.service.plan(request=terminate())

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))

    plan_id, outcomes, emitted_on = rig.finished[0]
    assert plan_id == plan.plan_id
    assert outcomes == (StepOutcome(order=1, status=StepStatus.DONE),)
    assert emitted_on == threading.get_ident()
    assert rig.executor.threads and rig.executor.threads[0] != threading.get_ident()
    assert rig.executor.plans == [plan]


def test_execute_does_not_block_the_main_loop(rigs: RigFactory) -> None:
    executor = FakeExecutor(gate=threading.Event())
    rig = rigs.build(executor=executor)
    plan = rig.service.plan(request=terminate())

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)

    assert executor.started.wait(timeout=TIMEOUT_S)
    assert rig.finished == []
    executor.gate.set()
    spin_until(predicate=lambda: bool(rig.finished))


def test_second_execute_with_the_same_id_raises_plan_not_found(rigs: RigFactory) -> None:
    rig = rigs.build()
    plan = rig.service.plan(request=terminate())
    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)

    with pytest.raises(PlanNotFound):
        rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    assert len(rig.executor.plans) == 1


class OrphanVolumeScanner:
    """A disk scan that finds one orphan volume, so a volume removal can be planned."""

    def scan(self, *, config: Config) -> DiskReport:
        return report(docker=docker_disk(volumes=(disk_volume(name="pgdata"),)))

    def cancel(self) -> None:
        return None


def test_wrong_phrase_raises_mismatch_and_exact_phrase_then_runs(rigs: RigFactory) -> None:
    rig = rigs.build()
    rig.service.attach_disk_scanner(scanner=OrphanVolumeScanner())
    rig.service.rescan_disk()
    spin_until(predicate=lambda: rig.service.disk_report() is not None)
    plan = rig.service.plan(request=volume("pgdata"))
    assert plan.confirm_phrase == "pgdata"

    with pytest.raises(ConfirmationMismatch):
        rig.service.execute(plan_id=plan.plan_id, typed_confirmation="PGDATA")
    assert rig.executor.plans == []

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation="pgdata")
    spin_until(predicate=lambda: bool(rig.finished))
    assert rig.executor.plans == [plan]


def test_expired_plan_raises_plan_expired_using_the_injected_clock(rigs: RigFactory) -> None:
    rig = rigs.build()
    stale = rig.service.plan(request=terminate())
    rig.clock.now = stale.expires_at

    with pytest.raises(PlanExpired):
        rig.service.execute(plan_id=stale.plan_id, typed_confirmation=None)
    with pytest.raises(PlanNotFound):
        rig.service.execute(plan_id=stale.plan_id, typed_confirmation=None)

    fresh = rig.service.plan(request=terminate())
    assert fresh.created_at == stale.expires_at
    rig.service.execute(plan_id=fresh.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    assert rig.executor.plans == [fresh]


def test_rejected_plan_emits_action_rejected_and_no_outcome(rigs: RigFactory) -> None:
    rig = rigs.build(executor=FakeExecutor(error=TargetChanged()))
    plan = rig.service.plan(request=terminate())

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.rejected))

    assert rig.rejected[0][0] == plan.plan_id
    assert isinstance(rig.rejected[0][1], TargetChanged)
    assert rig.finished == []


def test_actions_and_sampling_share_one_worker_so_they_never_overlap(rigs: RigFactory) -> None:
    rig = rigs.build()
    rig.sampler.proceed.clear()
    rig.sampler.entered.clear()
    rig.service.request_cycle()
    assert rig.sampler.entered.wait(timeout=TIMEOUT_S)
    plan = rig.service.plan(request=terminate())

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)

    assert not rig.executor.started.wait(timeout=0.2)
    rig.sampler.proceed.set()
    assert rig.executor.started.wait(timeout=TIMEOUT_S)
    spin_until(predicate=lambda: bool(rig.finished))


def test_reclaim_delta_is_measured_on_a_later_snapshot_after_an_immediate_cycle(
    rigs: RigFactory,
) -> None:
    base = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)))
    before = with_free_space(snapshot=base, available=400, free=900)
    after = with_free_space(snapshot=base, available=700, free=950)
    rig = rigs.build(base=before)
    plan = rig.service.plan(request=terminate())
    calls = rig.sampler.calls
    rig.sampler.current = after

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.measured))

    assert rig.measured == [(plan.plan_id, ReclaimDelta(freed_ram=300, freed_disk=50))]
    assert rig.sampler.calls > calls
    assert rig.service.snapshot() == after


def test_a_sample_already_in_flight_when_the_delay_elapses_is_not_used_for_the_delta(
    rigs: RigFactory,
) -> None:
    base = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)))
    before = with_free_space(snapshot=base, available=400, free=900)
    after = with_free_space(snapshot=base, available=700, free=950)
    rig = rigs.build(base=before)
    plan = rig.service.plan(request=terminate())
    rig.sampler.proceed.clear()
    rig.sampler.entered.clear()
    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    assert rig.sampler.entered.wait(timeout=TIMEOUT_S)

    rig.sampler.current = after
    spin_for(seconds=0.1)
    assert rig.measured == []
    rig.sampler.proceed.set()
    spin_until(predicate=lambda: bool(rig.measured))

    assert rig.measured == [(plan.plan_id, ReclaimDelta(freed_ram=300, freed_disk=50))]


def test_plan_without_actions_or_snapshot_raises_invalid_request() -> None:
    bare = AppService(sampler=FakeSampler(), config=Config())
    equipped = AppService(
        sampler=FakeSampler(),
        config=Config(),
        actions=ActionSetup(executor=FakeExecutor(), owner_uid=OWNER_UID),
    )
    try:
        with pytest.raises(InvalidRequest):
            bare.plan(request=terminate())
        with pytest.raises(InvalidRequest):
            equipped.plan(request=terminate())
        with pytest.raises(InvalidRequest):
            bare.execute(plan_id=PlanId("x"), typed_confirmation=None)
    finally:
        bare.stop()
        equipped.stop()


def test_completion_after_stop_is_discarded(rigs: RigFactory) -> None:
    executor = FakeExecutor(gate=threading.Event())
    rig = rigs.build(executor=executor)
    plan = rig.service.plan(request=terminate())
    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    assert executor.started.wait(timeout=TIMEOUT_S)
    stopper = threading.Thread(target=rig.service.stop)
    stopper.start()

    executor.gate.set()
    stopper.join(timeout=TIMEOUT_S)
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(may_block=False)

    assert rig.finished == []
    with pytest.raises(InvalidRequest):
        rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)


def test_stop_returns_at_once_while_an_action_is_still_running(rigs: RigFactory) -> None:
    executor = FakeExecutor(gate=threading.Event())
    rig = rigs.build(executor=executor)
    plan = rig.service.plan(request=terminate())
    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    assert executor.started.wait(timeout=TIMEOUT_S)

    began = monotonic()
    rig.service.stop()
    elapsed = monotonic() - began

    executor.gate.set()
    assert elapsed < 1.0
    assert rig.finished == []


def test_each_plan_is_measured_against_its_own_baseline(rigs: RigFactory) -> None:
    base = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)))
    s0 = with_free_space(snapshot=base, available=400, free=900)
    s1 = with_free_space(snapshot=base, available=500, free=910)
    s2 = with_free_space(snapshot=base, available=700, free=950)
    rig = rigs.build(base=s0)
    first = rig.service.plan(request=terminate())
    second = rig.service.plan(request=terminate())
    rig.sampler.proceed.clear()
    rig.sampler.entered.clear()
    rig.sampler.current = s1
    rig.service.execute(plan_id=first.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    assert rig.sampler.entered.wait(timeout=TIMEOUT_S)
    spin_for(seconds=0.1)

    # `second` queues behind the sample in flight, which will publish s1.
    rig.service.execute(plan_id=second.plan_id, typed_confirmation=None)
    rig.sampler.current = s2
    rig.sampler.proceed.set()
    spin_until(predicate=lambda: len(rig.measured) == 2)

    assert rig.measured == [
        (first.plan_id, ReclaimDelta(freed_ram=300, freed_disk=50)),
        (second.plan_id, ReclaimDelta(freed_ram=200, freed_disk=40)),
    ]
