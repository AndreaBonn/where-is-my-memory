from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import SLOTTED_FROZEN_ERROR, invalid_model_value
from wimm import model as m
from wimm.model import (
    ACTION_TARGET_SHAPES,
    ActionKind,
    ActionOffer,
    ActionRequest,
    ActivityAssessment,
    ActivityState,
    Category,
    ComposeFingerprint,
    ContainerFingerprint,
    DirFingerprint,
    DockerStatus,
    GroupId,
    ImageFingerprint,
    MemoryUse,
    Plan,
    PlanId,
    PlanStep,
    ProcessFingerprint,
    Protection,
    Risk,
    TargetId,
    TargetShape,
    VolumeFingerprint,
    protection_of,
    require_aware,
)

NOW = datetime(2026, 10, 16, tzinfo=UTC)


# The mass action over a chosen set needs its ids: it has its own tests in test_actions_selected.
@pytest.mark.parametrize("kind", [k for k in ActionKind if k is not ActionKind.DISK_FREE_SELECTED])
def test_request_target_shapes_and_exclusions(kind: ActionKind) -> None:
    shape = ACTION_TARGET_SHAPES[kind]
    request = ActionRequest(
        kind=kind,
        group_id=GroupId("g") if shape is TargetShape.GROUP else None,
        target_id=TargetId("t") if shape is TargetShape.TARGET else None,
    )
    assert request.kind is kind
    invalid = {"group_id": GroupId("g"), "target_id": TargetId("t")}
    with pytest.raises(ValueError, match=r"target|group|shape"):
        ActionRequest(kind=kind, **invalid_model_value(invalid))
    if shape is not TargetShape.NONE:
        with pytest.raises(ValueError, match=r"target|group|shape"):
            ActionRequest(kind=kind)
    if kind in {
        ActionKind.STOP_ALL_IDLE_SAFE,
        ActionKind.GROUP_STOP,
        ActionKind.IMAGES_PRUNE_DANGLING,
        ActionKind.IMAGES_PRUNE_UNUSED,
        ActionKind.CONTAINERS_PRUNE_STOPPED,
        ActionKind.DISK_FREE_SAFE,
    }:
        assert replace(request, excluded_ids=frozenset({"x"})).excluded_ids == {"x"}
    else:
        with pytest.raises(ValueError, match="excluded_ids"):
            replace(request, excluded_ids=frozenset({"x"}))


def make_plan(risk: Risk = Risk.SAFE) -> Plan:
    step = PlanStep(
        order=1,
        kind=ActionKind.IMAGE_REMOVE,
        target_label="image",
        fingerprint=ImageFingerprint(id="sha256:a"),
        risk=risk,
    )
    return Plan(
        plan_id=PlanId("p"),
        request=ActionRequest(kind=ActionKind.IMAGE_REMOVE, target_id=TargetId("image")),
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=120),
        steps=(step,),
        consequences=("Si riscarica.",),
        estimated_reclaim_ram=0,
        estimated_reclaim_disk=10,
        confirm_phrase="image" if risk is Risk.DANGER else None,
    )


@pytest.mark.parametrize("risk", list(Risk))
def test_plan_derived_risk_confirmation_and_order(risk: Risk) -> None:
    plan = make_plan(risk=risk)
    assert plan.risk is risk
    with pytest.raises(ValueError, match="confirm_phrase"):
        replace(plan, confirm_phrase=None if risk is Risk.DANGER else "image")
    with pytest.raises(ValueError, match="steps"):
        replace(plan, steps=())
    with pytest.raises(ValueError, match="order"):
        replace(plan, steps=(replace(plan.steps[0], order=2),))
    assert replace(plan, steps=(*plan.steps, replace(plan.steps[0], order=2))).risk is risk


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", NOW.replace(tzinfo=None)),
        ("expires_at", NOW),
        ("estimated_reclaim_ram", -1),
        ("estimated_reclaim_disk", 1.5),
        ("consequences", ["mutable"]),
        ("steps", []),
    ],
)
def test_plan_invalid_fields(field: str, value: object) -> None:
    plan = make_plan()
    assert plan.estimated_reclaim_disk == 10
    with pytest.raises(ValueError, match=field):
        replace(plan, **invalid_model_value({field: value}))


def test_risk_order() -> None:
    assert Risk.SAFE < Risk.CAUTION < Risk.DANGER
    assert not Risk.DANGER < Risk.CAUTION
    assert max([Risk.SAFE, Risk.DANGER, Risk.CAUTION]) is Risk.DANGER
    assert max([Risk.SAFE, Risk.CAUTION]) is Risk.CAUTION
    assert min([Risk.DANGER, Risk.CAUTION]) is Risk.CAUTION


@pytest.mark.parametrize("category", list(Category))
def test_protection_derived_from_category(category: Category) -> None:
    expected = (
        Protection.PROTECTED
        if category in {Category.SYSTEM, Category.SESSION, Category.SELF}
        else Protection.ACTIONABLE
    )
    assert protection_of(category=category) is expected


@pytest.mark.parametrize("state", list(ActivityState))
def test_activity_requires_reason_and_aware_since(state: ActivityState) -> None:
    activity = ActivityAssessment(state=state, since=NOW, reason="Osservato")
    assert activity.since == NOW
    with pytest.raises(ValueError, match="reason"):
        replace(activity, reason=" ")
    with pytest.raises(ValueError, match="since"):
        replace(activity, since=NOW.replace(tzinfo=None))
    if state is ActivityState.UNKNOWN:
        assert replace(activity, since=None).since is None
    else:
        with pytest.raises(ValueError, match="since"):
            replace(activity, since=None)


@pytest.mark.parametrize("value", [-1, 0.5, True])
def test_byte_counts_are_nonnegative_integers(value: object) -> None:
    memory = MemoryUse(used=1, reclaimable=2)
    assert memory.reclaimable > memory.used
    with pytest.raises(ValueError, match="used"):
        replace(memory, used=invalid_model_value(value))


def test_docker_status_and_datetime_contract() -> None:
    assert DockerStatus(available=True, error=None).available
    assert DockerStatus(available=False, error="Daemon fermo").error == "Daemon fermo"
    for available, error in [(True, "Errore"), (False, None), (False, "")]:
        with pytest.raises(ValueError, match="error"):
            DockerStatus(available=available, error=error)
    assert require_aware(value=NOW, field="clock") == NOW
    with pytest.raises(ValueError, match="clock"):
        require_aware(value=NOW.replace(tzinfo=None), field="clock")


@pytest.mark.parametrize(
    "fingerprint",
    [
        ProcessFingerprint(pid=1, create_time=123.125, uid=1000, cmdline_hash="hash"),
        ContainerFingerprint(id="c", status="running"),
        ComposeFingerprint(project="demo", container_ids=frozenset({"a", "b"})),
        ImageFingerprint(id="i"),
        VolumeFingerprint(name="v", created_at="2026-10-01T10:00:00Z"),
        DirFingerprint(realpath="/projects/demo", st_ino=1, st_dev=2),
    ],
)
def test_fingerprints_are_frozen_slotted_and_step_targets(fingerprint: m.Fingerprint) -> None:
    assert not hasattr(fingerprint, "__dict__")
    with pytest.raises((TypeError, FrozenInstanceError), match=SLOTTED_FROZEN_ERROR):
        invalid_model_value(fingerprint).extra = "mutation"


def test_compose_fingerprint_rejects_mutable_ids() -> None:
    assert ComposeFingerprint(project="p", container_ids=frozenset({"a"})).container_ids == {"a"}
    with pytest.raises(ValueError, match="container_ids"):
        ComposeFingerprint(project="p", container_ids=invalid_model_value({"a"}))


def test_action_offer_rejects_mutation() -> None:
    offer = ActionOffer(kind=ActionKind.CONTAINER_STOP, risk=Risk.SAFE)
    with pytest.raises(FrozenInstanceError):
        invalid_model_value(offer).risk = Risk.DANGER
    assert offer.risk is Risk.SAFE


@pytest.mark.parametrize(
    "field,value",
    [
        ("consequences", "not a tuple"),
        ("consequences", frozenset({"item"})),
        ("steps", frozenset({make_plan().steps[0]})),
    ],
)
def test_plan_requires_exact_collection_shapes(field: str, value: object) -> None:
    plan = make_plan()
    assert plan.consequences == ("Si riscarica.",)
    with pytest.raises(ValueError, match=field):
        replace(plan, **invalid_model_value({field: value}))


def test_plan_risk_uses_all_steps_and_rejects_empty_confirmation() -> None:
    plan = make_plan(risk=Risk.DANGER)
    safe_step = replace(plan.steps[0], risk=Risk.SAFE)
    danger_step = replace(plan.steps[0], order=2)
    mixed = replace(plan, steps=(safe_step, danger_step))
    assert mixed.risk is Risk.DANGER
    assert replace(mixed, steps=(safe_step,), confirm_phrase=None).risk is Risk.SAFE
    with pytest.raises(ValueError, match="confirm_phrase"):
        replace(mixed, confirm_phrase="")
    with pytest.raises(ValueError, match="confirm_phrase"):
        replace(mixed, confirm_phrase="  ")


def test_action_catalog_is_exact() -> None:
    assert {kind.value for kind in ActionKind} == {
        "process_terminate",
        "process_kill",
        "app_close",
        "container_stop",
        "container_remove",
        "group_stop",
        "compose_down",
        "compose_down_volumes",
        "stop_all_idle_safe",
        "image_remove",
        "images_prune_dangling",
        "images_prune_unused",
        "builder_prune",
        "containers_prune_stopped",
        "volume_remove",
        "cache_clean",
        "cache_item_remove",
        "trash_empty",
        "devdir_delete",
        "disk_free_safe",
        "disk_free_selected",
        "container_start",
        "restart_stopped",
    }


def test_action_target_shape_map_is_complete() -> None:
    assert ACTION_TARGET_SHAPES == {
        ActionKind.PROCESS_TERMINATE: TargetShape.TARGET,
        ActionKind.PROCESS_KILL: TargetShape.TARGET,
        ActionKind.APP_CLOSE: TargetShape.GROUP,
        ActionKind.CONTAINER_STOP: TargetShape.TARGET,
        ActionKind.CONTAINER_REMOVE: TargetShape.TARGET,
        ActionKind.GROUP_STOP: TargetShape.GROUP,
        ActionKind.COMPOSE_DOWN: TargetShape.GROUP,
        ActionKind.COMPOSE_DOWN_VOLUMES: TargetShape.GROUP,
        ActionKind.STOP_ALL_IDLE_SAFE: TargetShape.NONE,
        ActionKind.IMAGE_REMOVE: TargetShape.TARGET,
        ActionKind.IMAGES_PRUNE_DANGLING: TargetShape.NONE,
        ActionKind.IMAGES_PRUNE_UNUSED: TargetShape.NONE,
        ActionKind.BUILDER_PRUNE: TargetShape.NONE,
        ActionKind.CONTAINERS_PRUNE_STOPPED: TargetShape.NONE,
        ActionKind.VOLUME_REMOVE: TargetShape.TARGET,
        ActionKind.CACHE_CLEAN: TargetShape.TARGET,
        ActionKind.CACHE_ITEM_REMOVE: TargetShape.TARGET,
        ActionKind.TRASH_EMPTY: TargetShape.NONE,
        ActionKind.DEVDIR_DELETE: TargetShape.TARGET,
        ActionKind.DISK_FREE_SAFE: TargetShape.NONE,
        ActionKind.DISK_FREE_SELECTED: TargetShape.NONE,
        ActionKind.CONTAINER_START: TargetShape.TARGET,
        ActionKind.RESTART_STOPPED: TargetShape.TARGET,
    }


def test_pressure_and_step_outcome_catalogs_are_exact() -> None:
    assert {state.value for state in m.Pressure} == {"ok", "warning", "critical"}
    assert {state.value for state in m.StepOutcome} == {
        "ok",
        "already_gone",
        "not_responding",
        "failed",
    }
