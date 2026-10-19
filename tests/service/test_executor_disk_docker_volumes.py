import logging

import pytest

from tests.service.executor_disk_docker_helpers import (
    GB,
    IMAGE_ID,
    executor_for,
)
from tests.service.executor_fakes import (
    VOLUME_CREATED_AT,
    FakeDocker,
    builder_step,
    container_step,
    image_step,
    make_plan,
    volume_step,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveContainer, LiveImage, LiveVolume, StepStatus
from wimm.service.errors import DockerUnavailable, TargetChanged


def test_volume_without_containers_is_removed() -> None:
    docker = FakeDocker(
        volumes={"data": LiveVolume(name="data", in_use=False, created_at=VOLUME_CREATED_AT)}
    )
    plan = make_plan(steps=[volume_step(order=1, name="data")])

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("remove_volume", "data")]


def test_volume_referenced_by_a_container_is_refused() -> None:
    docker = FakeDocker(
        volumes={"data": LiveVolume(name="data", in_use=True, created_at=VOLUME_CREATED_AT)}
    )
    plan = make_plan(steps=[volume_step(order=1, name="data")])

    with pytest.raises(TargetChanged):
        executor_for(docker=docker).execute(plan=plan)

    assert docker.calls == []


def test_volume_already_removed_is_reported_gone() -> None:
    plan = make_plan(steps=[volume_step(order=1, name="data")])

    outcomes = executor_for(docker=FakeDocker()).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]


def test_builder_prune_returns_the_space_the_daemon_reports() -> None:
    docker = FakeDocker(cache_freed=3 * GB)

    outcomes = executor_for(docker=docker).execute(plan=make_plan(steps=[builder_step(order=1)]))

    assert [(o.status, o.freed_bytes) for o in outcomes] == [(StepStatus.DONE, 3 * GB)]
    assert docker.calls == [("prune_build_cache", "")]


def test_disk_steps_without_docker_are_unavailable() -> None:
    plan = make_plan(steps=[builder_step(order=1)])

    with pytest.raises(DockerUnavailable):
        executor_for(docker=None).execute(plan=plan)


def test_prune_of_stopped_containers_runs_one_remove_per_container() -> None:
    docker = FakeDocker(
        live={i: LiveContainer(id=i, status="exited") for i in ("c1", "c2")},
    )
    steps = [
        container_step(order=n, container_id=i, kind=ActionKind.CONTAINER_REMOVE, status="exited")
        for n, i in enumerate(("c1", "c2"), start=1)
    ]
    plan = make_plan(steps=steps, request_kind=ActionKind.CONTAINERS_PRUNE_STOPPED)

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.DONE]
    assert docker.calls == [("remove", "c1:v=False"), ("remove", "c2:v=False")]


def test_prune_step_for_a_container_started_again_rejects_the_plan() -> None:
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="running")})
    step = container_step(
        order=1, container_id="c1", kind=ActionKind.CONTAINER_REMOVE, status="exited"
    )
    plan = make_plan(steps=[step], request_kind=ActionKind.CONTAINERS_PRUNE_STOPPED)

    with pytest.raises(TargetChanged):
        executor_for(docker=docker).execute(plan=plan)

    assert docker.calls == []


def test_every_executed_disk_step_logs_action_target_outcome_and_bytes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    docker = FakeDocker(
        images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False)},
        cache_freed=2048,
    )
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID), builder_step(order=2)])

    with caplog.at_level(logging.INFO, logger="wimm.service.executor_disk_docker"):
        executor_for(docker=docker).execute(plan=plan)

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert lines == [
        f"disk action=image_remove target={IMAGE_ID} outcome=done freed_bytes=unknown",
        "disk action=builder_prune target=build cache outcome=done freed_bytes=2048",
    ]


def test_container_remove_outside_a_disk_prune_is_not_logged_as_disk_action(
    caplog: pytest.LogCaptureFixture,
) -> None:
    docker = FakeDocker(live={"c1": LiveContainer(id="c1", status="exited")})
    step = container_step(
        order=1, container_id="c1", kind=ActionKind.CONTAINER_REMOVE, status="exited"
    )

    with caplog.at_level(logging.INFO, logger="wimm.service.executor_disk_docker"):
        executor_for(docker=docker).execute(plan=make_plan(steps=[step]))

    assert caplog.records == []
