import threading

import pytest

from tests.service.executor_fakes import (
    OWNER_UID,
    FakeDocker,
    FakeProcesses,
    container_step,
    live_process,
    make_plan,
    process_step,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveContainer, StepStatus
from wimm.service.errors import ControlFailed, DockerUnavailable, TargetChanged
from wimm.service.executor import PlanExecutor

STOP = ActionKind.CONTAINER_STOP
REMOVE = ActionKind.CONTAINER_REMOVE
BARRIER_TIMEOUT_S = 5


class RendezvousDocker(FakeDocker):
    """Stop only completes if two stops are in flight at once, i.e. they run in parallel."""

    def __init__(self, *, ids: list[str]) -> None:
        super().__init__(live={i: LiveContainer(id=i, status="running") for i in ids})
        self.barrier = threading.Barrier(len(ids))

    def stop(self, *, container_id: str, timeout_s: int) -> None:
        try:
            self.barrier.wait(timeout=BARRIER_TIMEOUT_S)
        except threading.BrokenBarrierError as error:
            raise ControlFailed("stops did not overlap") from error
        super().stop(container_id=container_id, timeout_s=timeout_s)


def running(*ids: str) -> FakeDocker:
    return FakeDocker(live={i: LiveContainer(id=i, status="running") for i in ids})


def build_executor(
    *, docker: FakeDocker | None, processes: FakeProcesses | None = None
) -> PlanExecutor:
    return PlanExecutor(
        processes=processes or FakeProcesses(), containers=docker, owner_uid=OWNER_UID
    )


def test_stop_container_uses_a_ten_second_timeout() -> None:
    docker = running("c1")
    plan = make_plan(steps=[container_step(order=1, container_id="c1", kind=STOP)])

    outcomes = build_executor(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("stop", "c1:10")]


def test_container_whose_state_changed_rejects_the_plan_before_any_action() -> None:
    # Planned as a stopped container to remove; it has been started again meanwhile.
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="running")})
    processes = FakeProcesses(live={4321: live_process(pid=4321)})
    steps = [
        process_step(order=1, pid=4321),
        container_step(order=2, container_id="c1", kind=REMOVE, status="exited"),
    ]

    with pytest.raises(TargetChanged):
        build_executor(docker=docker, processes=processes).execute(plan=make_plan(steps=steps))

    assert docker.calls == [] and processes.signals == []


def test_container_already_stopped_by_the_user_counts_as_done_for_a_stop() -> None:
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="exited")})
    processes = FakeProcesses(live={4321: live_process(pid=4321)})
    steps = [
        process_step(order=1, pid=4321),
        container_step(order=2, container_id="c1", kind=STOP),
    ]

    outcomes = build_executor(docker=docker, processes=processes).execute(
        plan=make_plan(steps=steps)
    )

    assert [o.status for o in outcomes][1] is StepStatus.ALREADY_GONE
    assert docker.calls == []
    assert processes.signals  # the rest of the plan still ran


def test_missing_container_is_already_gone_and_the_plan_continues() -> None:
    docker = running("c2")
    steps = [
        container_step(order=1, container_id="missing", kind=STOP),
        container_step(order=2, container_id="c2", kind=STOP),
    ]

    outcomes = build_executor(docker=docker).execute(plan=make_plan(steps=steps))

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE, StepStatus.DONE]


def test_remove_of_a_stopped_container_keeps_volumes() -> None:
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="exited")})
    step = container_step(order=1, container_id="c1", kind=REMOVE, status="exited")
    plan = make_plan(steps=[step])

    outcomes = build_executor(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("remove", "c1:v=False")]


def test_remove_of_a_running_container_is_refused_without_calls() -> None:
    docker = running("c1")
    plan = make_plan(steps=[container_step(order=1, container_id="c1", kind=REMOVE)])

    outcomes = build_executor(docker=docker).execute(plan=plan)

    assert outcomes[0].status is StepStatus.FAILED
    assert outcomes[0].message is not None and "running" in outcomes[0].message
    assert docker.calls == []


def test_stop_then_remove_in_one_plan_removes_the_now_stopped_container() -> None:
    docker = running("c1")
    steps = [
        container_step(order=1, container_id="c1", kind=STOP),
        container_step(order=2, container_id="c1", kind=REMOVE),
    ]

    outcomes = build_executor(docker=docker).execute(plan=make_plan(steps=steps))

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.DONE]
    assert [call[0] for call in docker.calls] == ["stop", "remove"]


def test_container_stops_run_in_parallel() -> None:
    docker = RendezvousDocker(ids=["c1", "c2"])
    steps = [container_step(order=n, container_id=f"c{n}", kind=STOP) for n in (1, 2)]

    outcomes = build_executor(docker=docker).execute(plan=make_plan(steps=steps))

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.DONE]


def test_failed_container_stop_does_not_prevent_the_others() -> None:
    docker = running("c1", "c2")
    docker.failing = frozenset({"c1"})
    steps = [container_step(order=n, container_id=f"c{n}", kind=STOP) for n in (1, 2)]

    outcomes = build_executor(docker=docker).execute(plan=make_plan(steps=steps))

    assert [o.status for o in outcomes] == [StepStatus.FAILED, StepStatus.DONE]


def test_group_plan_terminates_processes_before_stopping_containers() -> None:
    docker = running("c1")
    processes = FakeProcesses(live={4321: live_process(pid=4321)})
    steps = [
        container_step(order=2, container_id="c1", kind=STOP),
        process_step(order=1, pid=4321),
    ]
    ordered = make_plan(steps=sorted(steps, key=lambda step: step.order))

    outcomes = build_executor(docker=docker, processes=processes).execute(plan=ordered)

    assert [o.order for o in outcomes] == [1, 2]
    assert processes.signals and docker.calls


def test_container_plan_without_docker_raises_before_touching_processes() -> None:
    processes = FakeProcesses(live={4321: live_process(pid=4321)})
    steps = [
        process_step(order=1, pid=4321),
        container_step(order=2, container_id="c1", kind=STOP),
    ]

    with pytest.raises(DockerUnavailable):
        build_executor(docker=None, processes=processes).execute(plan=make_plan(steps=steps))

    assert processes.signals == []


def test_unexpected_exception_in_a_container_step_is_a_failed_step() -> None:
    docker = FakeDocker(
        live={
            "c1": LiveContainer(id="c1", status="running"),
            "c2": LiveContainer(id="c2", status="running"),
        },
        crashing=frozenset({"c1"}),
    )
    plan = make_plan(
        steps=[
            container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_STOP),
            container_step(order=2, container_id="c2", kind=ActionKind.CONTAINER_STOP),
        ]
    )
    executor = PlanExecutor(processes=FakeProcesses(), containers=docker, owner_uid=OWNER_UID)

    outcomes = executor.execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.FAILED, StepStatus.DONE]
