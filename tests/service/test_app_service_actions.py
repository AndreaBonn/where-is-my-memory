import threading

import pytest

from tests.core.disk_helpers import docker_disk, report
from tests.core.disk_helpers import volume as disk_volume
from tests.service.app_service_actions_helpers import (
    FakeExecutor,
    RigFactory,
    rigs,
    terminate,
    volume,
)
from tests.service.service_helpers import (
    TIMEOUT_S,
    spin_until,
)
from wimm.config import Config
from wimm.model.actions import Plan
from wimm.model.disk import DiskReport
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.errors import (
    ConfirmationMismatch,
    ControlFailed,
    PlanExpired,
    PlanNotFound,
    TargetChanged,
)

__all__ = ["rigs"]


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


class CrashingExecutor(FakeExecutor):
    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        raise RuntimeError("boom: internal detail")


def test_crashing_executor_surfaces_a_control_failed_not_the_raw_exception(
    rigs: RigFactory, caplog: pytest.LogCaptureFixture
) -> None:
    rig = rigs.build(executor=CrashingExecutor())
    plan = rig.service.plan(request=terminate())

    rig.service.execute(plan_id=plan.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.rejected))

    rejected_id, error = rig.rejected[0]
    assert rejected_id == plan.plan_id
    assert isinstance(error, ControlFailed)
    assert "boom" not in str(error)
    assert rig.finished == []
    assert "crashed" in caplog.text
