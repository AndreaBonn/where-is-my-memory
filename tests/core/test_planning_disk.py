import pytest

from tests.core.disk_helpers import (
    MB,
    VOLUME_CREATED_AT,
    devdir,
    docker_disk,
    image,
    report,
    stopped,
    volume,
)
from tests.core.planning_disk_helpers import _plan
from tests.core.planning_helpers import NOW, OWNER_UID, snapshot
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import (
    ActionRequest,
    ContainerFingerprint,
    DirFingerprint,
    ImageFingerprint,
    Plan,
    VolumeFingerprint,
)
from wimm.model.enums import ActionKind, PlanId, Risk
from wimm.model.errors import InvalidRequest


def test_devdir_delete_plans_one_step_with_directory_fingerprint() -> None:
    target = devdir(path="/w/old/node_modules", size=700 * MB)
    disk = report(devdirs=(target, devdir(path="/w/other/.venv")))

    plan = _plan(kind=ActionKind.DEVDIR_DELETE, disk=disk, target="/w/old/node_modules")

    assert [s.fingerprint for s in plan.steps] == [
        DirFingerprint(realpath="/w/old/node_modules", st_ino=77, st_dev=2049)
    ]
    assert plan.steps[0].kind is ActionKind.DEVDIR_DELETE
    assert plan.risk is Risk.CAUTION
    assert plan.confirm_phrase is None
    assert plan.estimated_reclaim_disk == 700 * MB


def test_devdir_delete_unknown_path_is_refused() -> None:
    disk = report(devdirs=(devdir(path="/w/old/node_modules"),))

    with pytest.raises(InvalidRequest, match="Unknown"):
        _plan(kind=ActionKind.DEVDIR_DELETE, disk=disk, target="/w/old/node_module")


def test_volume_remove_orphan_is_danger_and_confirmed_by_its_name() -> None:
    disk = report(docker=docker_disk(volumes=(volume(name="scratch", size=120 * MB),)))

    plan = _plan(kind=ActionKind.VOLUME_REMOVE, disk=disk, target="scratch")

    assert plan.risk is Risk.DANGER
    assert plan.confirm_phrase == "scratch"
    assert plan.steps[0].fingerprint == VolumeFingerprint(
        name="scratch", created_at=VOLUME_CREATED_AT
    )
    assert plan.estimated_reclaim_disk == 120 * MB


def test_volume_remove_refuses_a_volume_whose_creation_time_is_unknown() -> None:
    disk = report(docker=docker_disk(volumes=(volume(name="scratch", created_at=""),)))

    with pytest.raises(InvalidRequest, match="creation time"):
        _plan(kind=ActionKind.VOLUME_REMOVE, disk=disk, target="scratch")


def test_volume_remove_refuses_a_volume_in_use_or_unknown_to_the_report() -> None:
    disk = report(
        docker=docker_disk(volumes=(volume(name="pgdata", ref_count=1), volume(name="x")))
    )

    with pytest.raises(InvalidRequest, match="in use"):
        _plan(kind=ActionKind.VOLUME_REMOVE, disk=disk, target="pgdata")
    with pytest.raises(InvalidRequest, match="Unknown"):
        _plan(kind=ActionKind.VOLUME_REMOVE, disk=disk, target="ghost")


def test_prune_dangling_has_one_step_per_unused_dangling_image_and_none_for_used() -> None:
    gone = image(char="a", tags=(), dangling=True, size=5 * MB)
    gone_too = image(char="b", tags=(), dangling=True, size=3 * MB)
    used_dangling = image(char="c", tags=(), dangling=True, in_use=True)
    tagged_unused = image(char="d")
    disk = report(docker=docker_disk(images=(gone, gone_too, used_dangling, tagged_unused)))

    plan = _plan(kind=ActionKind.IMAGES_PRUNE_DANGLING, disk=disk)

    assert [s.fingerprint for s in plan.steps] == [
        ImageFingerprint(id=gone.id),
        ImageFingerprint(id=gone_too.id),
    ]
    assert {s.kind for s in plan.steps} == {ActionKind.IMAGE_REMOVE}
    assert plan.risk is Risk.SAFE
    assert plan.estimated_reclaim_disk == 8 * MB
    assert plan.request.kind is ActionKind.IMAGES_PRUNE_DANGLING


def test_prune_dangling_with_nothing_dangling_is_refused() -> None:
    disk = report(docker=docker_disk(images=(image(char="a"),)))

    with pytest.raises(InvalidRequest, match="no executable steps"):
        _plan(kind=ActionKind.IMAGES_PRUNE_DANGLING, disk=disk)


def test_prune_unused_covers_tagged_unused_and_skips_images_in_use() -> None:
    registry = image(char="a", size=9 * MB)
    local = image(char="b", local_build=True, size=4 * MB)
    used = image(char="c", in_use=True)
    disk = report(docker=docker_disk(images=(registry, local, used)))

    plan = _plan(kind=ActionKind.IMAGES_PRUNE_UNUSED, disk=disk)

    assert [s.fingerprint for s in plan.steps] == [
        ImageFingerprint(id=registry.id),
        ImageFingerprint(id=local.id),
    ]
    assert [s.risk for s in plan.steps] == [Risk.SAFE, Risk.CAUTION]
    assert plan.risk is Risk.CAUTION


def test_volume_remove_with_unknown_refcount_is_refused_next_to_the_orphan_that_plans() -> None:
    disk = report(
        docker=docker_disk(
            volumes=(volume(name="orphan", ref_count=0), volume(name="unknown", ref_count=None))
        )
    )

    assert _plan(kind=ActionKind.VOLUME_REMOVE, disk=disk, target="orphan").confirm_phrase == (
        "orphan"
    )
    with pytest.raises(InvalidRequest, match="unknown"):
        _plan(kind=ActionKind.VOLUME_REMOVE, disk=disk, target="unknown")


def test_prune_over_a_truncated_report_says_how_many_entries_stay_out() -> None:
    images = tuple(image(char=f"{n:x}", tags=(), dangling=True) for n in range(1, 201))
    note = (
        "Il report mostra le 200 voci più grandi: altre 60 restano "
        "e serve una nuova scansione dopo la pulizia."
    )
    truncated = report(docker=docker_disk(images=images, images_truncated=60))
    complete = report(docker=docker_disk(images=images))

    assert note in _plan(kind=ActionKind.IMAGES_PRUNE_DANGLING, disk=truncated).consequences
    assert not any(
        "nuova scansione" in line
        for line in _plan(kind=ActionKind.IMAGES_PRUNE_DANGLING, disk=complete).consequences
    )


def test_container_prune_notes_the_container_counter_not_the_image_one() -> None:
    disk = report(
        docker=docker_disk(
            containers=(stopped(cid="1"),), images_truncated=9, containers_truncated=4
        )
    )

    consequences = _plan(kind=ActionKind.CONTAINERS_PRUNE_STOPPED, disk=disk).consequences

    assert any("altre 4 restano" in line for line in consequences)
    assert not any("altre 9" in line for line in consequences)


@pytest.mark.parametrize("kind", [ActionKind.IMAGES_PRUNE_DANGLING, ActionKind.IMAGES_PRUNE_UNUSED])
def test_excluded_images_leave_the_prune_and_the_estimate(kind: ActionKind) -> None:
    keep, drop = (
        image(char="a", tags=(), dangling=True, size=5 * MB),
        image(char="b", tags=(), dangling=True, size=3 * MB),
    )
    request = ActionRequest(kind=kind, excluded_ids=frozenset({drop.id}))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=report(docker=docker_disk(images=(keep, drop))),
    )

    plan = plan_action(request=request, snapshot=snapshot(), context=context)

    assert [s.fingerprint for s in plan.steps] == [ImageFingerprint(id=keep.id)]
    assert plan.estimated_reclaim_disk == 5 * MB


def test_excluded_stopped_containers_leave_the_prune_and_excluding_all_is_refused() -> None:
    first, second = stopped(cid="1", size=10), stopped(cid="2", size=20)
    disk = report(docker=docker_disk(containers=(first, second)))

    def plan_without(*ids: str) -> Plan:
        request = ActionRequest(
            kind=ActionKind.CONTAINERS_PRUNE_STOPPED, excluded_ids=frozenset(ids)
        )
        context = PlanningContext(owner_uid=OWNER_UID, disk_report=disk)
        return plan_action(request=request, snapshot=snapshot(), context=context)

    plan = plan_without(first.id)

    assert [s.fingerprint for s in plan.steps] == [
        ContainerFingerprint(id=second.id, status="exited")
    ]
    assert plan.estimated_reclaim_disk == 20
    with pytest.raises(InvalidRequest):
        plan_without(first.id, second.id)
