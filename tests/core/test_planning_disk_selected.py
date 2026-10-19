"""T-6.27: one plan for the rows the user ticked, built by the single-row planners (S16, S17)."""

import pytest

from wimm.core.planning import PlanningContext, plan_action
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, DiskReport, ItemBlob
from wimm.model.actions import ActionRequest, Plan, selected_entry_id
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.model.errors import InvalidRequest

from .disk_helpers import MB, cache, docker_disk, image, report, sha, volume
from .planning_helpers import NOW, OWNER_UID, snapshot

HUB = "/home/u/.cache/huggingface"
XTTS = "models--coqui--XTTS-v2"
XTTS_ENTRY = selected_entry_id(kind=ActionKind.CACHE_ITEM_REMOVE, target_id=f"huggingface:{XTTS}")
BUILDER_ENTRY = selected_entry_id(kind=ActionKind.BUILDER_PRUNE, target_id=None)


def _item(*, item_id: str = XTTS) -> CacheItem:
    return CacheItem(
        id=item_id,
        title="coqui/XTTS-v2",
        path=f"{HUB}/hub/{item_id}",
        size=2000 * MB,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
        blobs=(ItemBlob(path="hub/blobs/3b/excl", size=MB, st_ino=77, st_dev=2049),),
    )


def _report() -> DiskReport:
    hub = CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path=HUB,
        size=3000 * MB,
        st_ino=11,
        st_dev=2049,
        items=(_item(),),
    )
    docker = docker_disk(
        images=(image(char="a", tags=(), dangling=True), image(char="c", in_use=True)),
        volumes=(volume(name="db"),),
        build_cache_size=100 * MB,
        build_cache_reclaimable=70 * MB,
    )
    return report(docker=docker, caches=(hub, cache(kind=CacheKind.UV, ino=12)))


def _plan(*entries: str, disk: DiskReport | None = None) -> Plan:
    request = ActionRequest(kind=ActionKind.DISK_FREE_SELECTED, selected_ids=frozenset(entries))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=_report() if disk is None else disk,
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)


def _single(*, kind: ActionKind, target: str | None) -> Plan:
    request = ActionRequest(kind=kind, target_id=None if target is None else TargetId(target))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=_report(),
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)


def test_a_model_and_the_build_cache_make_one_plan_of_two_steps_at_caution() -> None:
    plan = _plan(XTTS_ENTRY, BUILDER_ENTRY)

    assert {step.kind for step in plan.steps} == {
        ActionKind.BUILDER_PRUNE,
        ActionKind.CACHE_ITEM_REMOVE,
    }
    assert len(plan.steps) == 2
    assert plan.risk is Risk.CAUTION
    assert plan.confirm_phrase is None
    assert plan.request.kind is ActionKind.DISK_FREE_SELECTED


def test_every_step_is_the_one_the_single_action_plans() -> None:
    plan = _plan(XTTS_ENTRY, BUILDER_ENTRY)
    item = _single(kind=ActionKind.CACHE_ITEM_REMOVE, target=f"huggingface:{XTTS}")
    builder = _single(kind=ActionKind.BUILDER_PRUNE, target=None)

    by_kind = {step.kind: step for step in plan.steps}
    for single in (item, builder):
        step = single.steps[0]
        got = by_kind[step.kind]
        assert (got.target_label, got.fingerprint, got.risk) == (
            step.target_label,
            step.fingerprint,
            step.risk,
        )
    assert plan.estimated_reclaim_disk == (
        item.estimated_reclaim_disk + builder.estimated_reclaim_disk
    )
    assert set(plan.consequences) == set(item.consequences) | set(builder.consequences)


def test_steps_are_consecutive_and_the_plan_is_deterministic() -> None:
    first = _plan(XTTS_ENTRY, BUILDER_ENTRY)
    assert [step.order for step in first.steps] == [1, 2]
    assert _plan(BUILDER_ENTRY, XTTS_ENTRY) == first


def test_a_safe_only_selection_stays_safe() -> None:
    plan = _plan(BUILDER_ENTRY)
    assert plan.risk is Risk.SAFE


def test_a_danger_row_is_refused_and_told_to_be_removed_alone() -> None:
    volume_entry = selected_entry_id(kind=ActionKind.VOLUME_REMOVE, target_id="db")
    assert _single(kind=ActionKind.VOLUME_REMOVE, target="db").risk is Risk.DANGER
    with pytest.raises(InvalidRequest, match="alone"):
        _plan(BUILDER_ENTRY, volume_entry)
    with pytest.raises(InvalidRequest, match="alone"):
        _plan(volume_entry)


def test_a_whole_cache_and_one_of_its_items_are_refused_together() -> None:
    whole = selected_entry_id(kind=ActionKind.CACHE_CLEAN, target_id="huggingface")
    with pytest.raises(InvalidRequest, match="huggingface"):
        _plan(whole, XTTS_ENTRY)
    # Paired: the item of another cache sits fine beside a whole cache.
    uv = selected_entry_id(kind=ActionKind.CACHE_CLEAN, target_id="uv")
    assert len(_plan(uv, XTTS_ENTRY).steps) == 2


def test_the_whole_cache_alone_and_the_item_alone_are_each_accepted() -> None:
    whole = selected_entry_id(kind=ActionKind.CACHE_CLEAN, target_id="huggingface")
    assert _plan(whole).steps[0].kind is ActionKind.CACHE_CLEAN
    assert _plan(XTTS_ENTRY).steps[0].kind is ActionKind.CACHE_ITEM_REMOVE


@pytest.mark.parametrize("entry", ["", "nonsense", "process_kill|1", "image_remove|", "x|y"])
def test_a_malformed_or_unselectable_id_is_an_invalid_request(entry: str) -> None:
    with pytest.raises(InvalidRequest):
        _plan(entry, BUILDER_ENTRY)


def test_a_target_that_vanished_gives_the_single_planner_error() -> None:
    gone = selected_entry_id(kind=ActionKind.IMAGE_REMOVE, target_id=sha("f"))
    with pytest.raises(InvalidRequest, match="Unknown image"):
        _single(kind=ActionKind.IMAGE_REMOVE, target=sha("f"))
    with pytest.raises(InvalidRequest, match="Unknown image"):
        _plan(BUILDER_ENTRY, gone)
    present = selected_entry_id(kind=ActionKind.IMAGE_REMOVE, target_id=sha("a"))
    assert len(_plan(BUILDER_ENTRY, present).steps) == 2


def test_a_selected_image_in_use_is_refused_like_the_single_action() -> None:
    busy = selected_entry_id(kind=ActionKind.IMAGE_REMOVE, target_id=sha("c"))
    with pytest.raises(InvalidRequest, match="in use"):
        _plan(busy)


def test_without_a_disk_report_nothing_is_planned() -> None:
    request = ActionRequest(
        kind=ActionKind.DISK_FREE_SELECTED, selected_ids=frozenset({BUILDER_ENTRY})
    )
    context = PlanningContext(owner_uid=OWNER_UID, now=lambda: NOW, disk_report=None)
    with pytest.raises(InvalidRequest):
        plan_action(request=request, snapshot=snapshot(), context=context)
