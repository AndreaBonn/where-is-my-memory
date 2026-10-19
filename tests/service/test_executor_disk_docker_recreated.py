import logging
from dataclasses import replace

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
    image_step,
    make_plan,
    volume_step,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveImage, LiveVolume, StepStatus
from wimm.service.errors import TargetChanged, TargetGone


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


def test_a_free_safe_plan_runs_each_of_its_steps() -> None:
    # D2 composes the single disk steps; the executor runs them as it runs them alone.
    docker = FakeDocker(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False)}, cache_freed=GB)
    plan = make_plan(
        steps=[builder_step(order=1), image_step(order=2, image_id=IMAGE_ID)],
        request_kind=ActionKind.DISK_FREE_SAFE,
    )

    outcomes = executor_for(docker=docker).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.DONE]
    assert docker.calls == [("prune_build_cache", ""), ("remove_image", IMAGE_ID)]


def test_a_free_safe_plan_is_logged_step_by_step(caplog: pytest.LogCaptureFixture) -> None:
    docker = FakeDocker(cache_freed=GB)
    plan = make_plan(steps=[builder_step(order=1)], request_kind=ActionKind.DISK_FREE_SAFE)

    with caplog.at_level(logging.INFO, logger="wimm.service.executor_disk_docker"):
        executor_for(docker=docker).execute(plan=plan)

    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert lines == [f"disk action=builder_prune target=build cache outcome=done freed_bytes={GB}"]


def test_tag_that_no_longer_resolves_is_skipped_silently_and_the_others_are_untagged() -> None:
    class StaleListing(FakeDocker):
        """The inspect still lists `app:1`, which the daemon no longer resolves."""

        def inspect_image(self, *, image_id: str) -> LiveImage | None:
            live = super().inspect_image(image_id=image_id)
            if live is None or not live.tags:
                return live
            return replace(live, tags=("app:1", *live.tags))

    docker = StaleListing(images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:2",))})

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [(o.status, o.message) for o in outcomes] == [(StepStatus.DONE, None)]
    assert docker.calls == [("remove_image", "app:2")]
    assert IMAGE_ID not in docker.images


def test_tag_deleted_by_someone_else_while_untagging_is_not_a_failure() -> None:
    class TagRemovedMeanwhile(FakeDocker):
        def remove_image(self, *, ref: str) -> None:
            if ref != "app:1":
                super().remove_image(ref=ref)
                return
            image = self.images[IMAGE_ID]
            self.images[IMAGE_ID] = replace(image, tags=("app:2",))
            raise TargetGone()

    docker = TagRemovedMeanwhile(
        images={IMAGE_ID: LiveImage(id=IMAGE_ID, in_use=False, tags=("app:1", "app:2"))}
    )

    outcomes = executor_for(docker=docker).execute(
        plan=make_plan(steps=[image_step(order=1, image_id=IMAGE_ID)])
    )

    assert [(o.status, o.message) for o in outcomes] == [(StepStatus.DONE, None)]
    assert docker.calls == [("remove_image", "app:2")]
    assert IMAGE_ID not in docker.images
