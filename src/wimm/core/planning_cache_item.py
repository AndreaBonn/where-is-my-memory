"""Planner for removing one item of a cache, e.g. a HuggingFace model (S10). Pure, no I/O."""

from dataclasses import replace

from wimm.model.actions import ActionRequest, Fingerprint, ItemFingerprint
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind, DiskReport
from wimm.model.enums import ActionKind, CacheItemKind
from wimm.model.errors import InvalidRequest
from wimm.model.served_fingerprint import ServedModelFingerprint

from .item_tools import is_item_removable
from .ollama_names import is_valid_model_name
from .planning_drafts import Draft, assess_draft
from .risk import RiskTarget
from .row_consequence import row_consequence

__all__ = ["ITEM_TARGET_SEPARATOR", "plan_cache_item_remove"]

ITEM_TARGET_SEPARATOR = ":"


def _find_item(*, request: ActionRequest, report: DiskReport | None) -> tuple[CacheKind, CacheItem]:
    """The cache kind and the item named by `<cache kind>:<item id>` in the report."""
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
                    return entry.kind, item
    raise InvalidRequest(f"Unknown cache item {target}")


def _fingerprint(*, cache: CacheKind, item: CacheItem) -> Fingerprint:
    """Ollama models go by name, so a name that could reach an argv badly is refused here."""
    if item.kind is CacheItemKind.OLLAMA_MODEL and not is_valid_model_name(name=item.id):
        raise InvalidRequest(f"{item.title} is not a valid ollama model name")
    if cache is CacheKind.OLLAMA_SYSTEM:
        return ServedModelFingerprint(name=item.id, model_id=item.model_id)
    return ItemFingerprint(
        realpath=item.path, st_ino=item.st_ino, st_dev=item.st_dev, blobs=item.blobs
    )


def plan_cache_item_remove(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    """One step removing the item folder and the store blobs only it reaches (Q1=A)."""
    cache, item = _find_item(request=request, report=report)
    if not is_item_removable(item=item):
        raise InvalidRequest(f"{item.title} has no .ini beside it, its tool cannot remove it")
    target = RiskTarget(kind="cache_item", item_kind=item.kind)
    assessed = assess_draft(target=target, kind=ActionKind.CACHE_ITEM_REMOVE)
    text = row_consequence(action=ActionKind.CACHE_ITEM_REMOVE, target=target)
    return [
        Draft(
            owner_ids=frozenset({item.path}),
            kind=ActionKind.CACHE_ITEM_REMOVE,
            label=item.title,
            name=item.title,
            fingerprint=_fingerprint(cache=cache, item=item),
            assessed=replace(assessed, consequences=(text,)),
            reclaim_ram=0,
            reclaim_disk=item.size,
        )
    ]
