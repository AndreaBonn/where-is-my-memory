import pytest

from tests.core.planning_helpers import container, context, group, snapshot
from tests.service.compose_fakes import PROJECT, FakeCompose, compose_plan, compose_step
from tests.service.executor_fakes import FakeDocker, FakeProcesses, container_step, make_plan
from wimm.core.planning import plan_action
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, GroupId
from wimm.service.control_protocols import LiveContainer, StepStatus
from wimm.service.errors import DockerUnavailable, TargetChanged
from wimm.service.executor import PlanExecutor

DOWN = ActionKind.COMPOSE_DOWN
DOWN_VOLUMES = ActionKind.COMPOSE_DOWN_VOLUMES
IDS = frozenset({"c1", "c2"})
OWNER_UID = 1000


def build(*, compose: FakeCompose | None, docker: FakeDocker | None = None) -> PlanExecutor:
    return PlanExecutor(
        processes=FakeProcesses(), containers=docker, compose=compose, owner_uid=OWNER_UID
    )


def test_down_runs_without_volumes_when_the_container_set_matches() -> None:
    compose = FakeCompose(projects={PROJECT: IDS})

    outcomes = build(compose=compose).execute(plan=compose_plan(ids=IDS, kind=DOWN))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert compose.calls == [(PROJECT, False)]


def test_down_volumes_passes_the_volumes_flag() -> None:
    compose = FakeCompose(projects={PROJECT: IDS})

    outcomes = build(compose=compose).execute(plan=compose_plan(ids=IDS, kind=DOWN_VOLUMES))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert compose.calls == [(PROJECT, True)]


def test_extra_container_in_the_project_rejects_the_plan_without_acting() -> None:
    compose = FakeCompose(projects={PROJECT: IDS | {"c3"}})

    with pytest.raises(TargetChanged):
        build(compose=compose).execute(plan=compose_plan(ids=IDS))

    assert compose.calls == []


def test_missing_container_in_the_project_rejects_the_plan_without_acting() -> None:
    compose = FakeCompose(projects={PROJECT: frozenset({"c1"})})

    with pytest.raises(TargetChanged):
        build(compose=compose).execute(plan=compose_plan(ids=IDS))

    assert compose.calls == []


def test_changed_compose_step_blocks_the_other_steps_of_the_plan() -> None:
    compose = FakeCompose(projects={PROJECT: IDS | {"c3"}})
    docker = FakeDocker(live={"solo": LiveContainer(id="solo", status="running")})
    plan = make_plan(
        steps=[
            container_step(order=1, container_id="solo", kind=ActionKind.CONTAINER_STOP),
            compose_step(ids=IDS, order=2),
        ]
    )

    with pytest.raises(TargetChanged):
        build(compose=compose, docker=docker).execute(plan=plan)

    assert docker.calls == []


def test_project_without_containers_is_already_done() -> None:
    compose = FakeCompose(projects={})

    outcomes = build(compose=compose).execute(plan=compose_plan(ids=IDS))

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]
    assert compose.calls == []


def test_set_changed_after_revalidation_fails_the_step_without_acting() -> None:
    compose = FakeCompose(projects={PROJECT: IDS}, after_listing={PROJECT: IDS | {"c3"}})

    outcomes = build(compose=compose).execute(plan=compose_plan(ids=IDS))

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert compose.calls == []


def test_compose_failure_becomes_a_failed_outcome_with_the_reason() -> None:
    compose = FakeCompose(projects={PROJECT: IDS}, failing=frozenset({PROJECT}))

    outcomes = build(compose=compose).execute(plan=compose_plan(ids=IDS))

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert outcomes[0].message is not None
    assert "no such network" in outcomes[0].message


def test_compose_step_without_compose_control_raises_docker_unavailable() -> None:
    with pytest.raises(DockerUnavailable):
        build(compose=None).execute(plan=compose_plan(ids=IDS))


def test_plan_of_a_fused_group_runs_compose_on_the_project_not_the_folder_name() -> None:
    fused = group(
        gid="f",
        name="cartella",
        compose_project="whitebox",
        members=(container(cid="c1"), container(cid="c2")),
    )
    request = ActionRequest(kind=DOWN, group_id=GroupId("f"))
    plan = plan_action(request=request, snapshot=snapshot(fused), context=context())
    compose = FakeCompose(projects={"whitebox": IDS, "cartella": frozenset()})

    outcomes = build(compose=compose).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert compose.calls == [("whitebox", False)]
