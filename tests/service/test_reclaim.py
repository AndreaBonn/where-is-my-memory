from dataclasses import replace

from tests.core.planning_helpers import snapshot
from wimm.model.enums import PlanId
from wimm.model.snapshot import Snapshot
from wimm.service.actions import ReclaimDelta
from wimm.service.reclaim import ReclaimTracker

PLAN = PlanId("p1")
OTHER = PlanId("p2")


def sample(*, available: int, free: int) -> Snapshot:
    base = snapshot()
    return replace(
        base,
        memory=replace(base.memory, available=available),
        disk=replace(base.disk, free=free),
    )


def test_watch_without_a_snapshot_returns_false_and_never_becomes_due() -> None:
    tracker = ReclaimTracker()

    assert tracker.watch(plan_id=PLAN, before=None) is False
    tracker.mark_due(plan_id=PLAN)

    assert tracker.due_ids == frozenset()
    assert tracker.resolve(after=sample(available=9, free=9), plan_ids=frozenset({PLAN})) == []


def test_watch_with_a_snapshot_returns_true_and_waits_for_the_delay() -> None:
    tracker = ReclaimTracker()

    assert tracker.watch(plan_id=PLAN, before=sample(available=100, free=1000)) is True

    assert tracker.due_ids == frozenset()
    assert tracker.resolve(after=sample(available=150, free=900), plan_ids=frozenset({PLAN})) == []


def test_mark_due_on_an_unknown_id_is_a_no_op() -> None:
    tracker = ReclaimTracker()
    tracker.watch(plan_id=PLAN, before=sample(available=100, free=1000))

    tracker.mark_due(plan_id=OTHER)

    assert tracker.due_ids == frozenset()
    tracker.mark_due(plan_id=PLAN)
    assert tracker.due_ids == frozenset({PLAN})


def test_due_baseline_resolves_to_the_signed_deltas_once() -> None:
    tracker = ReclaimTracker()
    tracker.watch(plan_id=PLAN, before=sample(available=100, free=1000))
    tracker.mark_due(plan_id=PLAN)
    after = sample(available=250, free=900)

    first = tracker.resolve(after=after, plan_ids=frozenset({PLAN}))

    assert first == [(PLAN, ReclaimDelta(freed_ram=150, freed_disk=-100))]
    assert tracker.resolve(after=after, plan_ids=frozenset({PLAN})) == []
    assert tracker.due_ids == frozenset()


def test_resolve_only_returns_the_ids_the_caller_asked_for() -> None:
    tracker = ReclaimTracker()
    for plan_id in (PLAN, OTHER):
        tracker.watch(plan_id=plan_id, before=sample(available=10, free=10))
        tracker.mark_due(plan_id=plan_id)

    results = tracker.resolve(after=sample(available=15, free=10), plan_ids=frozenset({PLAN}))

    assert results == [(PLAN, ReclaimDelta(freed_ram=5, freed_disk=0))]
    assert tracker.due_ids == frozenset({OTHER})
