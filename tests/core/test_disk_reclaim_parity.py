"""The headline "recoverable" figure and the plans must count the same bytes."""

from wimm.core.disk_rules import safe_reclaimable_bytes
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId

from .disk_helpers import MB, cache, docker_disk, image, report
from .planning_helpers import NOW, OWNER_UID, snapshot


def _plan(*, kind: ActionKind, disk: DiskReport, target: str | None = None) -> Plan:
    request = ActionRequest(kind=kind, target_id=None if target is None else TargetId(target))
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
            image(char="a", size=50 * MB, unique_size=10 * MB, in_use=True),
            image(char="b", tags=(), size=8 * MB, unique_size=8 * MB, dangling=True),
            image(char="c", size=40 * MB, unique_size=15 * MB),
            image(char="d", size=30 * MB, unique_size=30 * MB, local_build=True),
        ),
        build_cache_size=90 * MB,
        build_cache_reclaimable=25 * MB,
    )
    caches = (
        cache(kind=CacheKind.UV, size=3 * MB),
        cache(kind=CacheKind.NPM, size=2 * MB),
        cache(kind=CacheKind.TRASH, size=11 * MB),
    )
    return report(docker=docker, caches=caches)


def _safe_plan_total(*, data: DiskReport) -> int:
    requests: list[tuple[ActionKind, str | None]] = [
        (ActionKind.CACHE_CLEAN, c.kind.value) for c in data.caches
    ]
    requests += [(ActionKind.IMAGE_REMOVE, i.id) for i in data.docker.images if not i.in_use]
    requests.append((ActionKind.BUILDER_PRUNE, None))
    requests.append((ActionKind.TRASH_EMPTY, None))
    plans = [
        _plan(kind=kind, disk=data, target=target)
        for kind, target in requests
        if not (kind is ActionKind.CACHE_CLEAN and target == CacheKind.TRASH.value)
    ]
    return sum(p.estimated_reclaim_disk for p in plans if p.risk is Risk.SAFE)


def test_safe_total_equals_the_sum_of_the_safe_plans() -> None:
    data = _mixed_report()

    assert safe_reclaimable_bytes(report=data) == (3 + 2 + 8 + 15 + 25) * MB
    assert _safe_plan_total(data=data) == safe_reclaimable_bytes(report=data)


def test_parity_excludes_what_the_plans_rate_above_safe() -> None:
    data = _mixed_report()
    local = _plan(kind=ActionKind.IMAGE_REMOVE, disk=data, target=data.docker.images[3].id)
    trash = _plan(kind=ActionKind.TRASH_EMPTY, disk=data)

    assert local.risk is not Risk.SAFE
    assert trash.risk is not Risk.SAFE
    assert local.estimated_reclaim_disk == 30 * MB
    assert safe_reclaimable_bytes(report=data) < (3 + 2 + 8 + 15 + 25 + 30 + 11) * MB
