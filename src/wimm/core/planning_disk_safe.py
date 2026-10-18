"""D2: one plan with every disk item rated safe, built from the single-item drafts.

The steps are the ones the single actions plan (cache clean, build cache prune, image
removal), so the executor rechecks each of them as usual. Only `safe` drafts are kept:
the same ratings `safe_reclaimable_bytes` sums for the header.
"""

from wimm.core.cache_catalog import COMMAND_ONLY_KINDS
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, Risk, TargetId
from wimm.model.errors import InvalidRequest

from .planning_disk import plan_builder_prune, plan_cache_clean, plan_image_remove
from .planning_drafts import Draft


def _single(*, kind: ActionKind, target: str | None) -> ActionRequest:
    return ActionRequest(kind=kind, target_id=None if target is None else TargetId(target))


def _candidates(*, report: DiskReport) -> list[Draft]:
    drafts: list[Draft] = []
    for entry in report.caches:
        # An empty cache has nothing to free: no step of 0 B in the dialog.
        offered = entry.kind is not CacheKind.TRASH and entry.kind not in COMMAND_ONLY_KINDS
        if offered and entry.size > 0:
            request = _single(kind=ActionKind.CACHE_CLEAN, target=entry.kind.value)
            drafts += plan_cache_clean(request=request, report=report)
    docker = report.docker
    if not docker.status.available:
        return drafts
    if docker.build_cache_reclaimable > 0:
        drafts += plan_builder_prune(
            request=_single(kind=ActionKind.BUILDER_PRUNE, target=None), report=report
        )
    for image in docker.images:
        if not image.in_use:
            request = _single(kind=ActionKind.IMAGE_REMOVE, target=image.id)
            drafts += plan_image_remove(request=request, report=report)
    return drafts


def plan_disk_free_safe(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    """Every safe cache, the build cache and the safe unused images, minus the excluded ones."""
    if report is None:
        raise InvalidRequest("Disk report not available yet")
    return [
        draft
        for draft in _candidates(report=report)
        if draft.risk is Risk.SAFE and not draft.owner_ids & request.excluded_ids
    ]
