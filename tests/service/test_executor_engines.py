import pytest

from tests.service.compose_fakes import PROJECT, FakeCompose, compose_plan
from tests.service.executor_fakes import (
    OWNER_UID,
    FakeDocker,
    FakeProcesses,
    builder_step,
    container_step,
    live_process,
    make_plan,
    process_step,
)
from wimm.model.actions import EngineIdentity
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveContainer, StepStatus
from wimm.service.errors import TargetChanged
from wimm.service.executor import PlanExecutor

DOCKER = EngineIdentity(path="/var/run/docker.sock", st_ino=10, st_dev=5)
PODMAN = EngineIdentity(path="/run/user/1000/podman/podman.sock", st_ino=20, st_dev=5)
IDS = frozenset({"c1"})


def _docker(*, identities: tuple[EngineIdentity, ...]) -> FakeDocker:
    live = {"c1": LiveContainer(id="c1", status="running")}
    return FakeDocker(live=live, identities=identities)


def _executor(*, docker: FakeDocker, compose: FakeCompose | None = None) -> PlanExecutor:
    return PlanExecutor(
        processes=FakeProcesses(), containers=docker, compose=compose, owner_uid=OWNER_UID
    )


@pytest.mark.parametrize(
    "now",
    [
        (PODMAN,),
        (EngineIdentity(path=DOCKER.path, st_ino=11, st_dev=5),),
        (EngineIdentity(path=DOCKER.path, st_ino=10, st_dev=6),),
        (DOCKER, PODMAN),
        (),
    ],
)
def test_container_stop_is_rejected_when_the_engines_differ(
    now: tuple[EngineIdentity, ...],
) -> None:
    docker = _docker(identities=now)
    plan = make_plan(
        steps=[container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_STOP)],
        engines=(DOCKER,),
    )

    with pytest.raises(TargetChanged):
        _executor(docker=docker).execute(plan=plan)

    assert docker.calls == []
    assert docker.live["c1"].status == "running"


def test_container_stop_runs_when_the_engines_are_the_same_in_any_order() -> None:
    docker = _docker(identities=(PODMAN, DOCKER))
    plan = make_plan(
        steps=[container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_STOP)],
        engines=(DOCKER, PODMAN),
    )

    outcomes = _executor(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert [name for name, _ in docker.calls] == ["stop"]
    assert docker.live["c1"].status == "exited"


def test_disk_docker_step_is_rejected_when_the_engine_changed() -> None:
    docker = _docker(identities=(PODMAN,))
    plan = make_plan(steps=[builder_step(order=1)], engines=(DOCKER,))

    with pytest.raises(TargetChanged):
        _executor(docker=docker).execute(plan=plan)

    assert docker.calls == []


def test_compose_down_is_rejected_when_the_engine_changed() -> None:
    compose = FakeCompose(projects={PROJECT: IDS}, identities=(PODMAN,))
    plan = compose_plan(ids=IDS, kind=ActionKind.COMPOSE_DOWN, engines=(DOCKER,))

    with pytest.raises(TargetChanged):
        _executor(docker=_docker(identities=(PODMAN,)), compose=compose).execute(plan=plan)

    assert compose.calls == []


def test_a_process_plan_does_not_look_at_the_engines() -> None:
    processes = FakeProcesses()
    docker = _docker(identities=(PODMAN,))
    plan = make_plan(steps=[process_step(order=1, pid=100)], engines=(DOCKER,))
    processes.live[100] = live_process(pid=100)

    executor = PlanExecutor(processes=processes, containers=docker, owner_uid=OWNER_UID)

    outcomes = executor.execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
