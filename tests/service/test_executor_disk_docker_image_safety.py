import pytest

from tests.service.executor_disk_docker_helpers import (
    IMAGE_ID,
    OTHER_ID,
    executor_for,
    tagged_docker,
)
from tests.service.executor_fakes import (
    VOLUME_CREATED_AT,
    FakeDocker,
    builder_step,
    image_step,
    make_plan,
    volume_step,
)
from wimm.service.control_protocols import LiveImage, LiveVolume, StepStatus
from wimm.service.errors import ControlFailed, TargetChanged


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
