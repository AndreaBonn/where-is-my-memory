"""D2: one plan that frees, on the disk, everything rated safe and nothing else."""

import pytest

from wimm.core.disk_rules import safe_reclaimable_bytes, unavailable_docker
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.model.errors import InvalidRequest

from .disk_helpers import MB, cache, devdir, docker_disk, image, report, stopped, volume
from .planning_helpers import NOW, OWNER_UID, snapshot


def _plan(*, disk: DiskReport | None, excluded: frozenset[str] = frozenset()) -> Plan:
    request = ActionRequest(kind=ActionKind.DISK_FREE_SAFE, excluded_ids=excluded)
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=disk,
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)


def _mixed_report() -> DiskReport:
    docker = docker_disk(
        images=(
            image(char="a", tags=(), dangling=True, size=120 * MB),
            image(char="b", tags=("loc:1",), local_build=True, size=450 * MB),
            image(char="c", tags=("app:1",), in_use=True),
        ),
        volumes=(volume(name="db", size=50 * MB),),
        containers=(stopped(cid="d"),),
        build_cache_size=100 * MB,
        build_cache_reclaimable=70 * MB,
    )
    caches = (cache(kind=CacheKind.UV, size=3000 * MB), cache(kind=CacheKind.TRASH, ino=12))
    return report(docker=docker, caches=caches, devdirs=(devdir(path="/w/old/node_modules"),))


def test_plan_takes_every_safe_item_and_nothing_else() -> None:
    disk = _mixed_report()

    plan = _plan(disk=disk)

    assert sorted(step.kind.value for step in plan.steps) == [
        "builder_prune",
        "cache_clean",
        "image_remove",
    ]
    assert plan.risk is Risk.SAFE
    assert plan.confirm_phrase is None
    assert plan.estimated_reclaim_disk == (3000 + 70 + 120) * MB
    assert plan.estimated_reclaim_disk == safe_reclaimable_bytes(report=disk)


def test_excluded_items_are_left_out() -> None:
    plan = _plan(disk=_mixed_report(), excluded=frozenset({"/home/u/.cache/uv"}))

    assert "cache_clean" not in [step.kind.value for step in plan.steps]
    assert plan.estimated_reclaim_disk == (70 + 120) * MB


def test_without_docker_only_the_caches_are_planned() -> None:
    disk = report(docker=unavailable_docker(error="no socket"), caches=(cache(kind=CacheKind.NPM),))

    plan = _plan(disk=disk)

    assert [step.kind for step in plan.steps] == [ActionKind.CACHE_CLEAN]


@pytest.mark.parametrize("disk", [None, report()])
def test_nothing_safe_to_free_is_refused(disk: DiskReport | None) -> None:
    with pytest.raises(InvalidRequest):
        _plan(disk=disk)


def test_an_empty_cache_is_not_a_step() -> None:
    disk = report(caches=(cache(kind=CacheKind.UV, size=0), cache(kind=CacheKind.NPM, ino=12)))

    plan = _plan(disk=disk)

    assert [step.target_label for step in plan.steps] == ["/home/u/.cache/npm"]


def test_disk_free_safe_skips_caution_caches() -> None:
    disk = report(
        docker=unavailable_docker(error="no socket"),
        caches=(
            cache(kind=CacheKind.MAVEN, size=2000 * MB, ino=21),
            cache(kind=CacheKind.JETBRAINS, size=900 * MB, ino=22),
            cache(kind=CacheKind.UV, size=300 * MB, ino=23),
        ),
    )

    plan = _plan(disk=disk)

    assert [step.target_label for step in plan.steps] == ["/home/u/.cache/uv"]
    assert plan.risk is Risk.SAFE
    assert plan.estimated_reclaim_disk == 300 * MB
    assert safe_reclaimable_bytes(report=disk) == 300 * MB


def test_disk_free_safe_includes_the_safe_new_cache_types() -> None:
    kinds = (CacheKind.GRADLE, CacheKind.CARGO_REGISTRY, CacheKind.PLAYWRIGHT, CacheKind.GO_BUILD)
    caches = tuple(
        cache(kind=kind, size=10 * MB, ino=30 + index) for index, kind in enumerate(kinds)
    )
    disk = report(docker=unavailable_docker(error="no socket"), caches=caches)

    plan = _plan(disk=disk)

    assert len(plan.steps) == len(kinds)
    assert plan.estimated_reclaim_disk == 40 * MB == safe_reclaimable_bytes(report=disk)


def test_disk_free_safe_leaves_the_go_module_cache_to_its_own_command() -> None:
    disk = report(
        docker=unavailable_docker(error="no socket"),
        caches=(
            cache(kind=CacheKind.GO_MOD, size=500 * MB, ino=41),
            cache(kind=CacheKind.NPM, size=20 * MB, ino=42),
        ),
    )

    plan = _plan(disk=disk)

    assert [step.target_label for step in plan.steps] == ["/home/u/.cache/npm"]
    assert safe_reclaimable_bytes(report=disk) == 20 * MB


def test_a_single_clean_of_a_caution_cache_is_rated_caution() -> None:
    request = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("maven"))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=report(caches=(cache(kind=CacheKind.MAVEN, size=5 * MB),)),
    )

    plan = plan_action(request=request, snapshot=snapshot(), context=context)

    assert plan.risk is Risk.CAUTION
