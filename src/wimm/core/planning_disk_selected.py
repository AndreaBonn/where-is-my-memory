"""L6: one plan for the Disco rows the user ticked, built from the single-row drafts (S16).

Each ticked row is planned by the planner of its own action, so consequence, risk,
fingerprint and reclaim are those of the single action. A danger row is never part of a
selection (Q3=A): it is removed alone, with its typed phrase.
"""

from collections.abc import Callable

from wimm.model.actions import ActionRequest, parse_selected_entry
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest

from .planning_cache_item import ITEM_TARGET_SEPARATOR
from .planning_drafts import Draft

__all__ = ["plan_disk_free_selected"]


def _parse(*, entry: str) -> ActionRequest:
    try:
        return parse_selected_entry(entry=entry)
    except ValueError as err:
        raise InvalidRequest(f"Malformed selected entry {entry!r}") from err


def _refuse_cache_and_its_items(*, requests: list[ActionRequest]) -> None:
    """A whole cache and one of its items are never ticked together (S16)."""
    whole = {str(r.target_id) for r in requests if r.kind is ActionKind.CACHE_CLEAN}
    for request in requests:
        if request.kind is ActionKind.CACHE_ITEM_REMOVE:
            cache_kind = str(request.target_id).partition(ITEM_TARGET_SEPARATOR)[0]
            if cache_kind in whole:
                raise InvalidRequest(
                    f"Cache {cache_kind} and its item {request.target_id} "
                    "cannot be selected together"
                )


def plan_disk_free_selected(
    *, request: ActionRequest, plan_one: Callable[[ActionRequest], list[Draft]]
) -> list[Draft]:
    """The drafts of every ticked row, in a stable order.

    `plan_one` is the planner dispatch for a single request. A target gone from the
    report raises what the single planner raises for it.
    """
    requests = [_parse(entry=entry) for entry in sorted(request.selected_ids)]
    _refuse_cache_and_its_items(requests=requests)
    drafts = [draft for single in requests for draft in plan_one(single)]
    for draft in drafts:
        if draft.risk is Risk.DANGER:
            raise InvalidRequest(
                f"{draft.label} is a danger step: remove it alone, not in a selection"
            )
    return drafts
