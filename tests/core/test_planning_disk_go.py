from collections.abc import Callable

import pytest

from wimm.core.planning import PlanningContext, plan_action
from wimm.core.planning_disk import plan_cache_clean
from wimm.core.planning_tools import CacheToolMissing
from wimm.model.actions import ActionRequest, DirFingerprint
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.model.errors import InvalidRequest

from .disk_helpers import MB, cache, report
from .planning_helpers import NOW, OWNER_UID, snapshot

GO_MOD_REQUEST = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("go_mod"))
GO_BUILD_REQUEST = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId("go_build"))
DISK = report(
    caches=(
        cache(kind=CacheKind.GO_MOD, size=7 * MB, ino=51),
        cache(kind=CacheKind.GO_BUILD, size=3 * MB, ino=52),
    )
)


def _found(name: str) -> str:
    return f"/usr/bin/{name}"


def _missing(name: str) -> None:
    return None


def test_the_go_module_cache_is_planned_when_go_is_on_the_path() -> None:
    (draft,) = plan_cache_clean(request=GO_MOD_REQUEST, report=DISK, which=_found)

    assert draft.kind is ActionKind.CACHE_CLEAN
    assert draft.reclaim_disk == 7 * MB
    assert draft.fingerprint == DirFingerprint(
        realpath="/home/u/.cache/go_mod", st_ino=51, st_dev=2049
    )


def test_the_go_module_cache_is_not_offered_without_go_and_says_why() -> None:
    with pytest.raises(CacheToolMissing) as caught:
        plan_cache_clean(request=GO_MOD_REQUEST, report=DISK, which=_missing)

    assert isinstance(caught.value, InvalidRequest)
    assert caught.value.user_message == "Lo strumento che pulisce questa cache non è installato"


def test_the_go_build_cache_is_still_planned_without_go() -> None:
    (draft,) = plan_cache_clean(request=GO_BUILD_REQUEST, report=DISK, which=_missing)

    assert draft.reclaim_disk == 3 * MB


def _context(*, which: Callable[[str], str | None]) -> PlanningContext:
    return PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=DISK,
        which=which,
    )


def test_plan_action_offers_the_go_module_cache_by_the_path_of_the_context() -> None:
    plan = plan_action(request=GO_MOD_REQUEST, snapshot=snapshot(), context=_context(which=_found))

    assert [step.target_label for step in plan.steps] == ["/home/u/.cache/go_mod"]
    assert plan.risk is Risk.SAFE


def test_plan_action_refuses_the_go_module_cache_when_the_context_has_no_go() -> None:
    with pytest.raises(CacheToolMissing):
        plan_action(request=GO_MOD_REQUEST, snapshot=snapshot(), context=_context(which=_missing))
