from datetime import UTC, datetime, timedelta

import pytest

from tests.service.executor_fakes import make_plan, process_step
from wimm.model.actions import ActionRequest, Plan, PlanStep, VolumeFingerprint
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.service.errors import ConfirmationMismatch, PlanExpired, PlanNotFound
from wimm.service.plan_registry import PlanRegistry

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def make(*, plan_id: str, ttl_s: int = 120, phrase: str | None = None) -> Plan:
    if phrase is None:
        steps = make_plan(steps=[process_step(order=1, pid=5)]).steps
        request = ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId("5"))
    else:
        steps = (
            PlanStep(
                order=1,
                kind=ActionKind.VOLUME_REMOVE,
                target_label=phrase,
                fingerprint=VolumeFingerprint(name=phrase),
                risk=Risk.DANGER,
            ),
        )
        request = ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId(phrase))
    return Plan(
        plan_id=PlanId(plan_id),
        request=request,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=ttl_s),
        steps=steps,
        consequences=(),
        estimated_reclaim_ram=0,
        estimated_reclaim_disk=0,
        confirm_phrase=phrase,
    )


def test_take_returns_the_plan_once_then_not_found() -> None:
    registry = PlanRegistry()
    plan = make(plan_id="a")
    registry.add(plan=plan, now=NOW)

    taken = registry.take(plan_id=plan.plan_id, typed_confirmation=None, now=NOW)

    assert taken == plan
    with pytest.raises(PlanNotFound):
        registry.take(plan_id=plan.plan_id, typed_confirmation=None, now=NOW)


def test_take_unknown_id_raises_not_found() -> None:
    with pytest.raises(PlanNotFound):
        PlanRegistry().take(plan_id=PlanId("nope"), typed_confirmation=None, now=NOW)


def test_expired_plan_raises_expired_at_the_boundary_and_is_dropped() -> None:
    registry = PlanRegistry()
    registry.add(plan=make(plan_id="live"), now=NOW)
    registry.add(plan=make(plan_id="dead"), now=NOW)
    just_before = NOW + timedelta(seconds=119)

    assert registry.take(plan_id=PlanId("live"), typed_confirmation=None, now=just_before)
    with pytest.raises(PlanExpired):
        registry.take(
            plan_id=PlanId("dead"), typed_confirmation=None, now=NOW + timedelta(seconds=120)
        )
    with pytest.raises(PlanNotFound):
        registry.take(plan_id=PlanId("dead"), typed_confirmation=None, now=just_before)


def test_add_prunes_expired_plans() -> None:
    registry = PlanRegistry()
    registry.add(plan=make(plan_id="old", ttl_s=10), now=NOW)
    registry.add(plan=make(plan_id="fresh"), now=NOW + timedelta(seconds=11))

    assert len(registry) == 1


def test_wrong_phrase_raises_mismatch_without_consuming_the_plan() -> None:
    registry = PlanRegistry()
    plan = make(plan_id="d", phrase="pgdata")
    registry.add(plan=plan, now=NOW)

    for typed in (None, "", "PGDATA", "pgdata ", "pg"):
        with pytest.raises(ConfirmationMismatch):
            registry.take(plan_id=plan.plan_id, typed_confirmation=typed, now=NOW)

    assert registry.take(plan_id=plan.plan_id, typed_confirmation="pgdata", now=NOW) == plan


def test_phrase_is_ignored_when_the_plan_has_none() -> None:
    registry = PlanRegistry()
    plan = make(plan_id="s")
    registry.add(plan=plan, now=NOW)

    assert registry.take(plan_id=plan.plan_id, typed_confirmation="whatever", now=NOW) == plan
