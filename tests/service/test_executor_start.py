"""C4: starting again a container that a plan stopped."""

from tests.service.executor_fakes import (
    OWNER_UID,
    FakeDocker,
    FakeProcesses,
    container_step,
    make_plan,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveContainer, StepStatus
from wimm.service.executor import PlanExecutor

START = ActionKind.CONTAINER_START


def run(*, docker: FakeDocker) -> list[StepStatus]:
    executor = PlanExecutor(processes=FakeProcesses(), containers=docker, owner_uid=OWNER_UID)
    step = container_step(order=1, container_id="c1", kind=START, status="exited")
    plan = make_plan(steps=[step], request_kind=None)
    return [outcome.status for outcome in executor.execute(plan=plan)]


def test_a_stopped_container_is_started() -> None:
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="exited")})

    assert run(docker=docker) == [StepStatus.DONE]
    assert docker.calls == [("start", "c1")]
    assert docker.live["c1"].status == "running"


def test_a_container_already_running_again_is_left_alone() -> None:
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="running")})

    assert run(docker=docker) == [StepStatus.ALREADY_GONE]
    assert docker.calls == []


def test_a_container_removed_meanwhile_cannot_be_started_and_says_so() -> None:
    docker = FakeDocker()

    assert run(docker=docker) == [StepStatus.FAILED]
    assert docker.calls == []


def test_a_failing_start_fails_only_its_step() -> None:
    docker = FakeDocker(
        live={"c1": LiveContainer(id="c1", status="exited")}, failing=frozenset({"c1"})
    )

    assert run(docker=docker) == [StepStatus.FAILED]
