import pytest

from tests.core.disk_helpers import (
    MB,
    docker_disk,
    image,
    report,
    stopped,
)
from tests.core.planning_disk_helpers import _plan
from wimm.model.actions import (
    ContainerFingerprint,
    ImageFingerprint,
)
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest


def test_image_remove_assesses_the_single_image() -> None:
    local = image(char="a", local_build=True)
    used = image(char="b", in_use=True)
    disk = report(docker=docker_disk(images=(local, used)))

    plan = _plan(kind=ActionKind.IMAGE_REMOVE, disk=disk, target=local.id)

    assert plan.risk is Risk.CAUTION
    assert plan.steps[0].fingerprint == ImageFingerprint(id=local.id)
    with pytest.raises(InvalidRequest, match="in use"):
        _plan(kind=ActionKind.IMAGE_REMOVE, disk=disk, target=used.id)


def test_containers_prune_stopped_plans_removal_by_id() -> None:
    first, second = stopped(cid="1", size=2048), stopped(cid="2", state="created", size=0)
    disk = report(docker=docker_disk(containers=(first, second)))

    plan = _plan(kind=ActionKind.CONTAINERS_PRUNE_STOPPED, disk=disk)

    assert [s.fingerprint for s in plan.steps] == [
        ContainerFingerprint(id=first.id, status="exited"),
        ContainerFingerprint(id=second.id, status="created"),
    ]
    assert {s.kind for s in plan.steps} == {ActionKind.CONTAINER_REMOVE}
    assert plan.estimated_reclaim_disk == 2048


def test_builder_prune_is_a_single_step_without_fingerprint() -> None:
    disk = report(docker=docker_disk(build_cache_size=100 * MB))

    plan = _plan(kind=ActionKind.BUILDER_PRUNE, disk=disk)

    assert len(plan.steps) == 1
    assert plan.steps[0].fingerprint is None
    assert plan.steps[0].kind is ActionKind.BUILDER_PRUNE
    assert plan.risk is Risk.SAFE
    assert plan.estimated_reclaim_disk == 100 * MB


def test_builder_prune_reclaims_only_the_unshared_unused_part() -> None:
    disk = report(docker=docker_disk(build_cache_size=100 * MB, build_cache_reclaimable=30 * MB))

    plan = _plan(kind=ActionKind.BUILDER_PRUNE, disk=disk)

    assert plan.estimated_reclaim_disk == 30 * MB


def test_builder_prune_with_nothing_reclaimable_is_refused() -> None:
    disk = report(docker=docker_disk(build_cache_size=100 * MB, build_cache_reclaimable=0))

    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.BUILDER_PRUNE, disk=disk)


def test_image_remove_and_prune_reclaim_the_unique_size() -> None:
    shared = image(char="a", size=10 * MB, unique_size=4 * MB)
    dangling = image(char="b", tags=(), size=6 * MB, unique_size=6 * MB, dangling=True)
    disk = report(docker=docker_disk(images=(shared, dangling)))

    single = _plan(kind=ActionKind.IMAGE_REMOVE, disk=disk, target=shared.id)
    unused = _plan(kind=ActionKind.IMAGES_PRUNE_UNUSED, disk=disk)
    only_dangling = _plan(kind=ActionKind.IMAGES_PRUNE_DANGLING, disk=disk)

    assert single.estimated_reclaim_disk == 4 * MB
    assert unused.estimated_reclaim_disk == 10 * MB
    assert only_dangling.estimated_reclaim_disk == 6 * MB


def test_builder_prune_with_empty_cache_is_refused() -> None:
    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.BUILDER_PRUNE, disk=report())
