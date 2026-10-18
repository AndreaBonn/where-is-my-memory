"""R24, Q2=A: cleaning a model or Android folder is planned by its rating, DANGER typed."""

import pytest

from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import ActionRequest, DirFingerprint, Plan
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId

from .disk_helpers import MB, report
from .planning_helpers import NOW, OWNER_UID, snapshot

PATHS = {
    CacheKind.HUGGINGFACE: "/home/u/.cache/huggingface/hub",
    CacheKind.OLLAMA: "/home/u/.ollama/models",
    CacheKind.ANDROID_AVD: "/home/u/.android/avd",
    CacheKind.ANDROID_SDK: "/home/u/Android/Sdk",
}


def _plan_clean(*, kind: CacheKind) -> Plan:
    entry = CacheEntry(kind=kind, path=PATHS[kind], size=4000 * MB, st_ino=31, st_dev=2049)
    request = ActionRequest(kind=ActionKind.CACHE_CLEAN, target_id=TargetId(kind.value))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=report(caches=(entry,)),
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)


@pytest.mark.parametrize("kind", [CacheKind.OLLAMA, CacheKind.ANDROID_AVD])
def test_cleaning_a_danger_cache_needs_the_typed_path(kind: CacheKind) -> None:
    plan = _plan_clean(kind=kind)

    assert plan.risk is Risk.DANGER
    assert plan.confirm_phrase == PATHS[kind]
    assert plan.steps[0].fingerprint == DirFingerprint(realpath=PATHS[kind], st_ino=31, st_dev=2049)
    assert plan.estimated_reclaim_disk == 4000 * MB


@pytest.mark.parametrize("kind", [CacheKind.HUGGINGFACE, CacheKind.ANDROID_SDK])
def test_cleaning_a_caution_cache_needs_no_typed_phrase(kind: CacheKind) -> None:
    plan = _plan_clean(kind=kind)

    assert plan.risk is Risk.CAUTION
    assert plan.confirm_phrase is None
