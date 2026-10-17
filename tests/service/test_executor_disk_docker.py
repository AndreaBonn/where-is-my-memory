import logging

import pytest

from tests.service.executor_fakes import (
    OWNER_UID,
    VOLUME_CREATED_AT,
    FakeDocker,
    FakeProcesses,
    builder_step,
    container_step,
    image_step,
    make_plan,
    volume_step,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveContainer, LiveImage, LiveVolume, StepStatus
from wimm.service.errors import ControlFailed, DockerUnavailable, TargetChanged
from wimm.service.executor import PlanExecutor

IMAGE_ID = "sha256:" + "a" * 64
OTHER_ID = "sha256:" + "b" * 64
GB = 1_000_000_000


def executor_for(*, docker: FakeDocker | None) -> PlanExecutor:
    return PlanExecutor(processes=FakeProcesses(), containers=docker, owner_uid=OWNER_UID)


def image_docker(*, in_use: bool = False) -> FakeDocker:
    return FakeDocker(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=in_use)})


def test_unused_image_is_removed() -> None:
    docker = image_docker()
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("remove_image", IMAGE_ID)]
    assert IMAGE_ID not in docker.images


def test_image_now_used_by_a_container_rejects_the_plan_and_removes_nothing() -> None:
    docker = image_docker(in_use=True)
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    with pytest.raises(TargetChanged):
        executor_for(docker=docker).execute(plan=plan)

    assert docker.calls == []
    assert IMAGE_ID in docker.images


def test_image_that_became_used_between_validation_and_action_is_not_removed() -> None:
    class BecomesUsed(FakeDocker):
        def inspect_image(self, *, image_id: str) -> LiveImage | None:
            live = super().inspect_image(image_id=image_id)
            reads = sum(1 for call in self.calls if call[0] == "inspect")
            self.calls.append(("inspect", image_id))
            return live if reads == 0 else LiveImage(id=image_id, in_use=True)

    docker = BecomesUsed(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False)})
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert ("remove_image", IMAGE_ID) not in docker.calls


def tagged_docker(*tags: str) -> FakeDocker:
    return FakeDocker(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=tags)})


def test_image_with_two_tags_is_untagged_one_by_one_then_gone() -> None:
    docker = tagged_docker("app:1", "app:latest")
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("remove_image", "app:1"), ("remove_image", "app:latest")]
    assert IMAGE_ID not in docker.images


def test_image_that_survives_its_untags_is_removed_by_id() -> None:
    class KeepsImage(FakeDocker):
        def remove_image(self, *, ref: str) -> None:
            self.calls.append(("remove_image", ref))
            if ref == IMAGE_ID:
                self.images.pop(IMAGE_ID)

    docker = KeepsImage(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:1",))})

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("remove_image", "app:1"), ("remove_image", IMAGE_ID)]


def test_failed_untag_reports_the_tags_already_removed() -> None:
    docker = tagged_docker("app:1", "app:2", "app:3")
    docker_failing = FakeDocker(images=docker.images, failing_disk=frozenset({"app:3"}))
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    outcomes = executor_for(docker=docker_failing).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    message = outcomes[0].message or ""
    assert "app:1" in message and "app:2" in message
    assert "cannot remove app:3" in message
    assert IMAGE_ID in docker_failing.images


def test_image_gone_after_the_untags_is_not_removed_again() -> None:
    docker = tagged_docker("app:1")

    executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert ("remove_image", IMAGE_ID) not in docker.calls


def test_image_already_removed_is_reported_gone() -> None:
    docker = FakeDocker()
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]
    assert docker.calls == []


def test_failure_on_one_image_does_not_stop_the_next() -> None:
    docker = FakeDocker(
        images={i: LiveImage(id=i, in_use=False) for i in (IMAGE_ID, OTHER_ID)},
        failing_disk=frozenset({IMAGE_ID}),
    )
    plan = make_plan(
        steps=[image_step(order=1, image_id=IMAGE_ID), image_step(order=2, image_id=OTHER_ID)],
        request_kind=ActionKind.IMAGES_PRUNE_UNUSED,
    )

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.FAILED, StepStatus.DONE]
    assert docker.calls == [("remove_image", OTHER_ID)]


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


def test_tag_moved_to_another_image_after_the_inspect_is_skipped_and_named() -> None:
    class StaleTags(FakeDocker):
        def inspect_image(self, *, image_id: str) -> LiveImage | None:
            live = super().inspect_image(image_id=image_id)
            if live is None or image_id != IMAGE_ID:
                return live
            return LiveImage(id=live.id, in_use=False, tags=("app:1", "app:2"))

    docker = StaleTags(
        images={
            IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:1",)),
            OTHER_ID: LiveImage(id=OTHER_ID, in_use=False, tags=("app:2",)),
        }
    )

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert "app:2" in (outcomes[0].message or "")
    assert docker.calls == [("remove_image", "app:1")]
    assert docker.images[OTHER_ID].tags == ("app:2",)


def test_image_with_child_images_is_refused_and_keeps_its_tags() -> None:
    docker = FakeDocker(
        images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:1",), has_children=True)}
    )
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])

    with pytest.raises(TargetChanged):
        executor_for(docker=docker).execute(plan=plan)

    assert docker.calls == []
    assert docker.images[IMAGE_ID].tags == ("app:1",)


def test_image_that_gets_a_child_after_revalidation_is_not_untagged() -> None:
    class GainsChild(FakeDocker):
        def inspect_image(self, *, image_id: str) -> LiveImage | None:
            live = super().inspect_image(image_id=image_id)
            self.calls.append(("inspect", image_id))
            if live is None or len(self.calls) == 1:
                return live
            return LiveImage(id=live.id, in_use=False, tags=live.tags, has_children=True)

    docker = GainsChild(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:1",))})

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert [c for c in docker.calls if c[0] == "remove_image"] == []
    assert docker.images[IMAGE_ID].tags == ("app:1",)


def test_image_with_tags_and_digests_is_untagged_then_removed_by_id() -> None:
    docker = tagged_docker("app:1", "app:2")
    docker.digests[IMAGE_ID] = ("app@sha256:" + "c" * 64,)

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [
        ("remove_image", "app:1"),
        ("remove_image", "app:2"),
        ("remove_image", IMAGE_ID),
    ]
    assert IMAGE_ID not in docker.images


def test_digest_only_image_is_removed_by_id_without_untagging() -> None:
    docker = tagged_docker()
    docker.digests[IMAGE_ID] = ("app@sha256:" + "c" * 64,)

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert docker.calls == [("remove_image", IMAGE_ID)]
    assert IMAGE_ID not in docker.images


def test_daemon_conflict_on_the_id_removal_is_a_failed_step_with_its_message() -> None:
    class LateTag(FakeDocker):
        def remove_image(self, *, ref: str) -> None:
            if not self.calls:
                image = self.images[IMAGE_ID]
                self.images[IMAGE_ID] = LiveImage(
                    id=IMAGE_ID, in_use=False, tags=(*image.tags, "late:1", "late:2")
                )
            super().remove_image(ref=ref)

    docker = LateTag(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:1",))})

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    message = outcomes[0].message or ""
    assert "conflict" in message and "app:1" in message
    assert IMAGE_ID in docker.images


def test_image_that_vanishes_before_the_id_removal_is_reported_gone() -> None:
    class Phantom(FakeDocker):
        def inspect_image(self, *, image_id: str) -> LiveImage | None:
            return LiveImage(id=image_id, in_use=False)

    outcomes = executor_for(docker=Phantom()).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]


def test_volume_that_vanishes_before_the_removal_is_reported_gone() -> None:
    class Phantom(FakeDocker):
        def inspect_volume(self, *, name: str) -> LiveVolume | None:
            return LiveVolume(name=name, in_use=False, created_at=VOLUME_CREATED_AT)

    outcomes = executor_for(docker=Phantom()).execute(
        plan=make_plan(steps=[volume_step(order=1, name="data")])
    )

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]


def test_builder_prune_failure_is_a_failed_step_with_the_message() -> None:
    docker = FakeDocker(prune_error=ControlFailed("Cannot prune build cache: 404"))

    outcomes = executor_for(docker=docker).execute(plan=make_plan(steps=[builder_step(order=1)]))

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert "404" in (outcomes[0].message or "")


def _docker_with_volume(*, created_at: str) -> FakeDocker:
    return FakeDocker(
        volumes={"data": LiveVolume(name="data", in_use=False, created_at=created_at)}
    )


def test_volume_recreated_with_the_same_name_rejects_the_plan() -> None:
    docker = _docker_with_volume(created_at="2026-10-17T08:00:00Z")
    plan = make_plan(steps=[volume_step(order=1, name="data")])

    with pytest.raises(TargetChanged):
        executor_for(docker=docker).execute(plan=plan)

    assert docker.calls == []


@pytest.mark.parametrize(
    ("planned", "live"), [("", VOLUME_CREATED_AT), (VOLUME_CREATED_AT, ""), ("", "")]
)
def test_volume_without_a_known_creation_time_is_refused(planned: str, live: str) -> None:
    docker = _docker_with_volume(created_at=live)
    plan = make_plan(steps=[volume_step(order=1, name="data", created_at=planned)])

    with pytest.raises(TargetChanged):
        executor_for(docker=docker).execute(plan=plan)

    assert docker.calls == []


def test_volume_recreated_between_validation_and_action_is_not_removed() -> None:
    class Recreated(FakeDocker):
        def inspect_volume(self, *, name: str) -> LiveVolume | None:
            self.calls.append(("inspect_volume", name))
            stamp = VOLUME_CREATED_AT if len(self.calls) == 1 else "2026-10-17T08:00:00Z"
            return LiveVolume(name=name, in_use=False, created_at=stamp)

    docker = Recreated(volumes={"data": LiveVolume("data", False, VOLUME_CREATED_AT)})

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[volume_step(order=1, name="data")])
    )

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert ("remove_volume", "data") not in docker.calls


def test_a_disk_line_survives_an_exception_in_a_later_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Abort(BaseException):
        pass

    docker = FakeDocker(
        images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False)}, prune_error=Abort()
    )
    plan = make_plan(steps=[image_step(order=1, image_id=IMAGE_ID), builder_step(order=2)])

    logger = "wimm.service.executor_disk_docker"
    with caplog.at_level(logging.INFO, logger=logger), pytest.raises(Abort):
        executor_for(docker=docker).execute(plan=plan)

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert lines == [f"disk action=image_remove target={IMAGE_ID} outcome=done freed_bytes=unknown"]


def test_volume_creation_time_in_another_format_of_the_same_instant_is_accepted() -> None:
    docker = _docker_with_volume(created_at="2026-10-17T06:00:00Z")
    plan = make_plan(
        steps=[volume_step(order=1, name="data", created_at="2026-10-17T08:00:00+02:00")]
    )
    moved = _docker_with_volume(created_at="2026-10-17T06:00:01Z")

    executor_for(docker=docker).execute(plan=plan)
    with pytest.raises(TargetChanged):
        executor_for(docker=moved).execute(plan=plan)

    assert docker.calls != []
    assert moved.calls == []
