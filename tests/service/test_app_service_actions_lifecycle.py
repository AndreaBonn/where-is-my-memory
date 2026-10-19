import threading

import pytest
from gi.repository import GLib

from tests.core.planning_helpers import NOW, container, group, proc, snapshot
from tests.service.app_service_actions_helpers import (
    OWNER_UID,
    PID,
    FakeExecutor,
    RigFactory,
    rigs,
    terminate,
)
from tests.service.service_helpers import (
    TIMEOUT_S,
    FakeSampler,
    FixedClock,
    spin_until,
)
from wimm.config import Config
from wimm.model.actions import ActionRequest, EngineIdentity, Plan
from wimm.model.enums import ActionKind, Category, PlanId, TargetId
from wimm.service.actions import ActionSetup
from wimm.service.app_service import AppService
from wimm.service.errors import (
    InvalidRequest,
)

__all__ = ["rigs"]


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

    stopper = threading.Thread(target=rig.service.stop)
    stopper.start()
    stopper.join(timeout=TIMEOUT_S)
    returned_while_blocked = not stopper.is_alive()

    executor.gate.set()
    stopper.join(timeout=TIMEOUT_S)
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(may_block=False)
    assert returned_while_blocked
    assert rig.finished == []


def _plan_with_engine_probe(*, request: ActionRequest) -> tuple[Plan, list[int]]:
    engines = (EngineIdentity(path="/var/run/docker.sock", st_ino=10, st_dev=5),)
    reads: list[int] = []

    def identities() -> tuple[EngineIdentity, ...]:
        reads.append(1)
        return engines

    sampler = FakeSampler()
    sampler.proceed.set()
    sampler.current = snapshot(
        group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=PID),)),
        group(gid="db", category=Category.CONTAINER, members=(container(cid="up"),)),
    )
    setup = ActionSetup(executor=FakeExecutor(), owner_uid=OWNER_UID, engine_identities=identities)
    service = AppService(sampler=sampler, config=Config(), clock=FixedClock(NOW), actions=setup)
    service.start()
    try:
        spin_until(predicate=lambda: service.snapshot() is not None)
        plan = service.plan(request=request)
    finally:
        service.stop()
    return plan, reads


def test_plan_records_the_engines_the_actions_currently_use() -> None:
    stop = ActionRequest(kind=ActionKind.CONTAINER_STOP, target_id=TargetId("up"))
    plan, reads = _plan_with_engine_probe(request=stop)
    assert plan.engines == (EngineIdentity(path="/var/run/docker.sock", st_ino=10, st_dev=5),)
    assert reads == [1]


def test_a_process_plan_does_not_query_the_engines() -> None:
    # A stuck socket must never delay planning a kill that has nothing to do with Docker.
    plan, reads = _plan_with_engine_probe(request=terminate())
    assert plan.engines == ()
    assert reads == []
