"""C4: the service remembers which containers each recent plan really stopped."""

import logging
from dataclasses import replace

import pytest

from tests.core.planning_helpers import group, proc, snapshot
from tests.service.executor_fakes import CREATED_AT, container_step, make_plan, process_step
from wimm.core.planning_restart import StoppedContainer, StoppedProcess
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind, PlanId
from wimm.model.snapshot import Snapshot
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.restart_memory import RECENT_PLANS, StoppedContainers, StoppedProcesses

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


# F14: the commands of the processes a plan stopped, for «Copia comando di riavvio».
def process_plan(*, plan_id: str) -> Plan:
    steps = [process_step(order=1, pid=10), process_step(order=2, pid=11)]
    return replace(make_plan(steps=steps), plan_id=PlanId(plan_id))


def process_snapshot() -> Snapshot:
    first = replace(
        proc(pid=10),
        create_time=CREATED_AT,
        cmdline=("python3", "-m", "http.server"),
        cwd="/srv/a b",
    )
    second = replace(proc(pid=11), create_time=CREATED_AT, cmdline=("node", "x.js"), cwd="/srv/c")
    return snapshot(group(gid="g", members=(first, second)))


def test_records_stopped_process_commands() -> None:
    memory = StoppedProcesses()
    plan = process_plan(plan_id="p1")
    outcomes = (
        StepOutcome(order=1, status=StepStatus.DONE),
        StepOutcome(order=2, status=StepStatus.FAILED, message="boom"),
    )

    memory.note(plan=plan, snapshot=process_snapshot())
    memory.record(plan_id=plan.plan_id, outcomes=outcomes)

    assert memory.stopped == {
        "p1": (
            StoppedProcess(label="proc 10", argv=("python3", "-m", "http.server"), cwd="/srv/a b"),
        )
    }


def test_process_command_is_the_one_seen_at_planning_time() -> None:
    memory = StoppedProcesses()
    plan = process_plan(plan_id="p1")
    memory.note(plan=plan, snapshot=process_snapshot())
    later = snapshot(
        group(gid="g", members=(replace(proc(pid=10), create_time=CREATED_AT, cmdline=("other",)),))
    )

    memory.note(plan=replace(plan, plan_id=PlanId("p2")), snapshot=later)
    memory.record(plan_id=plan.plan_id, outcomes=all_done(plan=plan))

    assert memory.stopped["p1"][0].argv == ("python3", "-m", "http.server")


def test_unfinished_or_container_only_plans_leave_no_process() -> None:
    memory = StoppedProcesses()
    plan = stop_plan(plan_id="p1")

    memory.note(plan=plan, snapshot=process_snapshot())
    memory.record(plan_id=plan.plan_id, outcomes=())

    assert memory.stopped == {}


def test_only_the_last_plans_keep_process_commands() -> None:
    memory = StoppedProcesses()
    ids = [f"p{n}" for n in range(RECENT_PLANS + 2)]
    for plan_id in ids:
        plan = process_plan(plan_id=plan_id)
        memory.note(plan=plan, snapshot=process_snapshot())
        memory.record(plan_id=plan.plan_id, outcomes=all_done(plan=plan))

    assert list(memory.stopped) == ids[2:]


def test_process_memory_never_logs_the_command(caplog: pytest.LogCaptureFixture) -> None:
    memory = StoppedProcesses()
    plan = process_plan(plan_id="p1")
    secret = replace(
        proc(pid=10), create_time=CREATED_AT, cmdline=("run", "--token", "s3cr3t-value"), cwd="/srv"
    )

    with caplog.at_level(logging.INFO):
        memory.note(plan=plan, snapshot=snapshot(group(gid="g", members=(secret,))))
        memory.record(plan_id=plan.plan_id, outcomes=all_done(plan=plan))

    assert memory.stopped["p1"][0].argv == ("run", "--token", "s3cr3t-value")
    assert "s3cr3t-value" not in caplog.text
    assert "--token" not in caplog.text


def test_a_closed_app_records_its_restart_command() -> None:
    memory = StoppedProcesses()
    step = process_step(order=1, pid=10, kind=ActionKind.APP_CLOSE)
    plan = replace(make_plan(steps=[step]), plan_id=PlanId("p1"))

    memory.note(plan=plan, snapshot=process_snapshot())
    memory.record(plan_id=plan.plan_id, outcomes=all_done(plan=plan))

    assert memory.stopped == {
        "p1": (
            StoppedProcess(label="proc 10", argv=("python3", "-m", "http.server"), cwd="/srv/a b"),
        )
    }
    assert len(memory.commands(plan_id=plan.plan_id)) == 1
