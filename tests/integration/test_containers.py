import os
from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any

import pytest

from tests.integration.docker_targets import connect, exists, started_container
from tests.integration.live_targets import LIVE_ENGINES, container_step, single_step_plan
from tests.service.executor_fakes import make_plan
from wimm.collectors.docker_engines import FixedEngines
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus
from wimm.service.controls import DockerSdkControl, PsutilProcessControl
from wimm.service.executor import PlanExecutor

pytestmark = [pytest.mark.integration, pytest.mark.docker]
STOP = ActionKind.CONTAINER_STOP
REMOVE = ActionKind.CONTAINER_REMOVE
START = ActionKind.CONTAINER_START


@pytest.fixture
def client() -> Any:
    try:
        return connect()
    except RuntimeError as error:
        pytest.skip(str(error))


@pytest.fixture
def executor(client: Any) -> PlanExecutor:
    return PlanExecutor(
        processes=PsutilProcessControl(owner_uid=os.getuid()),
        containers=DockerSdkControl(engines=FixedEngines(client=client)),
        owner_uid=os.getuid(),
    )


@pytest.fixture
def two_containers(client: Any) -> Iterator[list[Any]]:
    with ExitStack() as stack:
        yield [stack.enter_context(started_container(client=client)) for _ in range(2)]


def test_container_created_by_the_test_is_stopped_then_removed(
    client: Any, executor: PlanExecutor
) -> None:
    with started_container(client=client) as container:
        stop = single_step_plan(step=container_step(container_id=container.id, kind=STOP))
        remove = single_step_plan(
            step=container_step(container_id=container.id, kind=REMOVE, status="exited")
        )

        stopped = executor.execute(plan=stop)
        container.reload()
        assert [o.status for o in stopped] == [StepStatus.DONE]
        assert container.status == "exited"

        removed = executor.execute(plan=remove)
        assert [o.status for o in removed] == [StepStatus.DONE]
        assert not exists(client=client, container_id=container.id)


def test_container_stopped_by_a_plan_is_started_again(client: Any, executor: PlanExecutor) -> None:
    with started_container(client=client) as container:
        stop = single_step_plan(step=container_step(container_id=container.id, kind=STOP))
        start = single_step_plan(
            step=container_step(container_id=container.id, kind=START, status="exited")
        )
        executor.execute(plan=stop)

        started = executor.execute(plan=start)

        container.reload()
        assert [o.status for o in started] == [StepStatus.DONE]
        assert container.status == "running"


def test_remove_of_a_running_container_is_refused_and_leaves_it_running(
    client: Any, executor: PlanExecutor
) -> None:
    with started_container(client=client) as container:
        plan = single_step_plan(step=container_step(container_id=container.id, kind=REMOVE))

        outcomes = executor.execute(plan=plan)

        container.reload()
        assert outcomes[0].status is StepStatus.FAILED
        assert container.status == "running"


def test_stopping_a_container_that_is_already_removed_is_already_gone(
    client: Any, executor: PlanExecutor
) -> None:
    with started_container(client=client) as container:
        container_id = container.id
        container.remove(force=True)

        plan = single_step_plan(step=container_step(container_id=container_id, kind=STOP))

        assert [o.status for o in executor.execute(plan=plan)] == [StepStatus.ALREADY_GONE]


def test_two_containers_are_stopped_in_one_plan(
    client: Any, executor: PlanExecutor, two_containers: list[Any]
) -> None:
    steps = [
        container_step(container_id=c.id, kind=STOP, order=n)
        for n, c in enumerate(two_containers, start=1)
    ]

    outcomes = executor.execute(plan=make_plan(steps=steps, engines=LIVE_ENGINES))

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.DONE]
    for container in two_containers:
        container.reload()
        assert container.status == "exited"
