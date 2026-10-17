import os
from pathlib import Path
from typing import Any

import pytest

from tests.integration.compose_targets import VOLUME_NAME, compose_project, project_resources
from tests.integration.docker_targets import connect
from tests.service.compose_fakes import compose_plan
from wimm.model.enums import ActionKind
from wimm.service.compose import DockerComposeControl, resolve_docker_binary
from wimm.service.control_protocols import StepStatus
from wimm.service.controls import DockerSdkControl, PsutilProcessControl
from wimm.service.errors import TargetChanged
from wimm.service.executor import PlanExecutor

pytestmark = [pytest.mark.integration, pytest.mark.docker]
DOWN = ActionKind.COMPOSE_DOWN
DOWN_VOLUMES = ActionKind.COMPOSE_DOWN_VOLUMES


@pytest.fixture
def client() -> Any:
    try:
        return connect()
    except RuntimeError as error:
        pytest.skip(str(error))


@pytest.fixture
def compose(client: Any) -> DockerComposeControl:
    return DockerComposeControl(client=client, docker_bin=resolve_docker_binary())


@pytest.fixture
def executor(client: Any, compose: DockerComposeControl) -> PlanExecutor:
    return PlanExecutor(
        processes=PsutilProcessControl(owner_uid=os.getuid()),
        containers=DockerSdkControl(client=client),
        compose=compose,
        owner_uid=os.getuid(),
    )


def test_down_removes_containers_and_network_and_keeps_the_volume(
    client: Any, compose: DockerComposeControl, executor: PlanExecutor, tmp_path: Path
) -> None:
    with compose_project(client=client, directory=tmp_path) as project:
        ids = compose.container_ids(project=project)
        before = project_resources(client=client, project=project)
        assert (len(before["containers"]), len(before["volumes"]), len(before["networks"])) == (
            2,
            1,
            1,
        )

        outcomes = executor.execute(plan=compose_plan(ids=ids, kind=DOWN, project=project))

        after = project_resources(client=client, project=project)
        assert [o.status for o in outcomes] == [StepStatus.DONE]
        assert (len(after["containers"]), len(after["networks"])) == (0, 0)
        assert [v.name for v in after["volumes"]] == [f"{project}_{VOLUME_NAME}"]


def test_down_volumes_also_removes_the_volume(
    client: Any, compose: DockerComposeControl, executor: PlanExecutor, tmp_path: Path
) -> None:
    with compose_project(client=client, directory=tmp_path) as project:
        ids = compose.container_ids(project=project)

        outcomes = executor.execute(plan=compose_plan(ids=ids, kind=DOWN_VOLUMES, project=project))

        after = project_resources(client=client, project=project)
        assert [o.status for o in outcomes] == [StepStatus.DONE]
        assert (len(after["containers"]), len(after["volumes"]), len(after["networks"])) == (
            0,
            0,
            0,
        )


def test_second_down_on_the_same_project_is_already_done(
    client: Any, compose: DockerComposeControl, executor: PlanExecutor, tmp_path: Path
) -> None:
    with compose_project(client=client, directory=tmp_path) as project:
        ids = compose.container_ids(project=project)
        plan = compose_plan(ids=ids, kind=DOWN, project=project)

        executor.execute(plan=plan)
        outcomes = executor.execute(plan=plan)

        assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]


def test_plan_with_a_different_container_set_changes_nothing(
    client: Any, compose: DockerComposeControl, executor: PlanExecutor, tmp_path: Path
) -> None:
    with compose_project(client=client, directory=tmp_path) as project:
        one = frozenset(sorted(compose.container_ids(project=project))[:1])

        with pytest.raises(TargetChanged):
            executor.execute(plan=compose_plan(ids=one, kind=DOWN, project=project))

        assert len(project_resources(client=client, project=project)["containers"]) == 2
