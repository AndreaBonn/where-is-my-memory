import pytest

from tests.service.executor_disk_docker_helpers import (
    IMAGE_ID,
    OTHER_ID,
    executor_for,
    tagged_docker,
)
from tests.service.executor_fakes import (
    FakeDocker,
    image_step,
    make_plan,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveImage, StepStatus
from wimm.service.errors import TargetChanged


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
