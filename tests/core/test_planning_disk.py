import pytest

from wimm.core.disk_rules import unavailable_docker
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import (
    ActionRequest,
    ContainerFingerprint,
    DirFingerprint,
    ImageFingerprint,
    Plan,
    VolumeFingerprint,
)
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.model.errors import InvalidRequest

from .disk_helpers import MB, SCANNED_AT, cache, devdir, docker_disk, image, report, stopped, volume
from .planning_helpers import NOW, OWNER_UID, snapshot


def _plan(*, kind: ActionKind, disk: DiskReport | None, target: str | None = None) -> Plan:
    request = ActionRequest(kind=kind, target_id=None if target is None else TargetId(target))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=disk,
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)


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
    assert plan.steps[0].fingerprint == VolumeFingerprint(name="scratch")
    assert plan.estimated_reclaim_disk == 120 * MB


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


def test_cache_clean_uses_the_directory_fingerprint_of_the_named_cache() -> None:
    uv = cache(kind=CacheKind.UV, size=3 * MB, ino=5, dev=9)
    disk = report(caches=(uv, cache(kind=CacheKind.NPM)))

    plan = _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target="uv")

    assert plan.steps[0].fingerprint == DirFingerprint(realpath=uv.path, st_ino=5, st_dev=9)
    assert plan.risk is Risk.SAFE
    assert plan.estimated_reclaim_disk == 3 * MB


def test_cache_clean_refuses_trash_and_missing_caches() -> None:
    disk = report(caches=(cache(kind=CacheKind.TRASH), cache(kind=CacheKind.UV)))

    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target="trash")
    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.CACHE_CLEAN, disk=disk, target="pip")


def test_trash_empty_is_danger_with_the_trash_label_as_phrase() -> None:
    trash = cache(kind=CacheKind.TRASH, size=40 * MB)

    plan = _plan(kind=ActionKind.TRASH_EMPTY, disk=report(caches=(trash,)))

    assert plan.risk is Risk.DANGER
    assert plan.confirm_phrase == "Cestino"
    assert plan.steps[0].fingerprint == DirFingerprint(realpath=trash.path, st_ino=11, st_dev=2049)
    assert plan.estimated_reclaim_disk == 40 * MB


@pytest.mark.parametrize(
    "kind",
    [
        ActionKind.IMAGES_PRUNE_DANGLING,
        ActionKind.IMAGES_PRUNE_UNUSED,
        ActionKind.CONTAINERS_PRUNE_STOPPED,
        ActionKind.BUILDER_PRUNE,
        ActionKind.TRASH_EMPTY,
    ],
)
def test_disk_actions_without_a_report_are_refused(kind: ActionKind) -> None:
    with pytest.raises(InvalidRequest, match="report"):
        _plan(kind=kind, disk=None)


def test_docker_actions_with_docker_unavailable_name_the_reason() -> None:
    disk = DiskReport(
        scanned_at=SCANNED_AT,
        docker=unavailable_docker(error="daemon stopped"),
        caches=(),
        devdirs=(),
    )

    with pytest.raises(InvalidRequest, match="daemon stopped"):
        _plan(kind=ActionKind.IMAGES_PRUNE_UNUSED, disk=disk)


def test_volume_remove_without_a_report_keeps_the_name_only_plan() -> None:
    plan = _plan(kind=ActionKind.VOLUME_REMOVE, disk=None, target="pgdata")

    assert plan.confirm_phrase == "pgdata"
    assert plan.estimated_reclaim_disk == 0
