"""Measure what an action freed: counters before it against a sample taken after."""

from dataclasses import dataclass

from wimm.model.enums import PlanId
from wimm.model.snapshot import Snapshot

from .actions import ReclaimDelta


@dataclass(frozen=True, slots=True)
class _Baseline:
    available: int
    free: int


class ReclaimTracker:
    """Pairs each executed plan with the counters of the snapshot it started from.

    A baseline moves from `watch` to *due* when the measuring delay has elapsed;
    `resolve` turns the chosen due ones into deltas against a later snapshot.
    """

    def __init__(self) -> None:
        self._waiting: dict[PlanId, _Baseline] = {}
        self._due: dict[PlanId, _Baseline] = {}

    @property
    def due_ids(self) -> frozenset[PlanId]:
        return frozenset(self._due)

    def watch(self, *, plan_id: PlanId, before: Snapshot | None) -> bool:
        """Remember the baseline; False if there was no snapshot to measure against."""
        if before is None:
            return False
        self._waiting[plan_id] = _Baseline(available=before.memory.available, free=before.disk.free)
        return True

    def mark_due(self, *, plan_id: PlanId) -> None:
        baseline = self._waiting.pop(plan_id, None)
        if baseline is not None:
            self._due[plan_id] = baseline

    def resolve(
        self, *, after: Snapshot, plan_ids: frozenset[PlanId]
    ) -> list[tuple[PlanId, ReclaimDelta]]:
        """Return and forget the deltas of the due baselines in `plan_ids` against `after`.

        The caller passes the ids that were due when the sample was submitted: a plan
        that became due later must wait for a sample taken after its own delay.
        """
        results: list[tuple[PlanId, ReclaimDelta]] = []
        for plan_id in plan_ids & self._due.keys():
            base = self._due.pop(plan_id)
            delta = ReclaimDelta(
                freed_ram=after.memory.available - base.available,
                freed_disk=after.disk.free - base.free,
            )
            results.append((plan_id, delta))
        return results
