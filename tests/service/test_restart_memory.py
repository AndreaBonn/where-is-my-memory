"""C4: the service remembers which containers each recent plan really stopped."""

from dataclasses import replace

from tests.service.executor_fakes import container_step, make_plan, process_step
from wimm.core.planning_restart import StoppedContainer
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind, PlanId
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.restart_memory import RECENT_PLANS, StoppedContainers

STOP = ActionKind.CONTAINER_STOP


def stop_plan(*, plan_id: str) -> Plan:
    steps = [
        process_step(order=1, pid=10),
        container_step(order=2, container_id="c1", kind=STOP),
        container_step(order=3, container_id="c2", kind=STOP),
    ]
    return replace(make_plan(steps=steps), plan_id=PlanId(plan_id))


def all_done(*, plan: Plan) -> tuple[StepOutcome, ...]:
    return tuple(StepOutcome(order=s.order, status=StepStatus.DONE) for s in plan.steps)


def test_only_containers_whose_stop_finished_are_remembered() -> None:
    memory = StoppedContainers()
    plan = stop_plan(plan_id="p1")
    outcomes = (
        StepOutcome(order=1, status=StepStatus.DONE),
        StepOutcome(order=2, status=StepStatus.DONE),
        StepOutcome(order=3, status=StepStatus.FAILED, message="boom"),
    )

    memory.track(plan=plan)
    memory.record(plan_id=plan.plan_id, outcomes=outcomes)

    assert memory.stopped == {"p1": (StoppedContainer(id="c1", label="c1"),)}


def test_a_plan_that_stopped_no_container_is_not_remembered() -> None:
    memory = StoppedContainers()
    plan = replace(make_plan(steps=[process_step(order=1, pid=10)]), plan_id=PlanId("p1"))

    memory.track(plan=plan)
    memory.record(plan_id=plan.plan_id, outcomes=all_done(plan=plan))

    assert memory.stopped == {}


def test_a_rejected_plan_is_forgotten_and_never_offered() -> None:
    memory = StoppedContainers()
    memory.track(plan=stop_plan(plan_id="p1"))

    memory.record(plan_id=PlanId("p1"), outcomes=())
    memory.record(plan_id=PlanId("p1"), outcomes=all_done(plan=stop_plan(plan_id="p1")))

    assert memory.stopped == {}


def test_only_the_most_recent_plans_are_kept() -> None:
    memory = StoppedContainers()
    ids = [f"p{n}" for n in range(RECENT_PLANS + 1)]
    for plan_id in ids:
        plan = stop_plan(plan_id=plan_id)
        memory.track(plan=plan)
        memory.record(plan_id=plan.plan_id, outcomes=all_done(plan=plan))

    assert list(memory.stopped) == ids[1:]
