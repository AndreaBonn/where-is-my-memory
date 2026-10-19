"""Planner for removing one item of a cache, e.g. a HuggingFace model (S10). Pure, no I/O."""

from dataclasses import replace

from wimm.model.actions import ActionRequest, ItemFingerprint
from wimm.model.cache_items import CacheItem
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind
from wimm.model.errors import InvalidRequest

from .planning_drafts import Draft, assess_draft
from .risk import RiskTarget
from .row_consequence import row_consequence

__all__ = ["ITEM_TARGET_SEPARATOR", "plan_cache_item_remove"]

ITEM_TARGET_SEPARATOR = ":"


def _find_item(*, request: ActionRequest, report: DiskReport | None) -> CacheItem:
    """The item named by `<cache kind>:<item id>` in the report."""
    target = str(request.target_id)
    kind, separator, item_id = target.partition(ITEM_TARGET_SEPARATOR)
    if not (separator and kind and item_id.strip()):
        raise InvalidRequest(f"Malformed cache item {target}")
    if report is None:
        raise InvalidRequest("Disk report not available yet")
    for entry in report.caches:
        if entry.kind.value == kind:
            for item in entry.items:
                if item.id == item_id:
                    return item
    raise InvalidRequest(f"Unknown cache item {target}")


def plan_cache_item_remove(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    """One step removing the item folder and the store blobs only it reaches (Q1=A)."""
    item = _find_item(request=request, report=report)
    target = RiskTarget(kind="cache_item", item_kind=item.kind)
    assessed = assess_draft(target=target, kind=ActionKind.CACHE_ITEM_REMOVE)
    text = row_consequence(action=ActionKind.CACHE_ITEM_REMOVE, target=target)
    return [
        Draft(
            owner_ids=frozenset({item.path}),
            kind=ActionKind.CACHE_ITEM_REMOVE,
            label=item.title,
            name=item.title,
            fingerprint=ItemFingerprint(
                realpath=item.path, st_ino=item.st_ino, st_dev=item.st_dev, blobs=item.blobs
            ),
            assessed=replace(assessed, consequences=(text,)),
            reclaim_ram=0,
            reclaim_disk=item.size,
        )
    ]
