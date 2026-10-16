"""Registry of plans waiting for confirmation (SPECIFICHE 8.1): one use, then gone."""

from datetime import datetime

from wimm.model.actions import Plan
from wimm.model.enums import PlanId

from .errors import ConfirmationMismatch, PlanExpired, PlanNotFound


class PlanRegistry:
    """Holds plans by id until they are executed or expire.

    Not thread-safe: the service touches it from the main loop only.
    """

    def __init__(self) -> None:
        self._plans: dict[PlanId, Plan] = {}

    def __len__(self) -> int:
        return len(self._plans)

    def add(self, *, plan: Plan, now: datetime) -> None:
        """Register a plan, dropping the ones already expired so the registry stays bounded."""
        self._plans = {pid: p for pid, p in self._plans.items() if p.expires_at > now}
        self._plans[plan.plan_id] = plan

    def take(self, *, plan_id: PlanId, typed_confirmation: str | None, now: datetime) -> Plan:
        """Remove and return a plan that may run now.

        A wrong confirmation phrase leaves the plan registered, so the user can retry;
        an expired plan is dropped. The phrase is compared exactly (case, whitespace).

        Raises
        ------
        PlanNotFound
            If the id is unknown, already executed or already expired and dropped.
        PlanExpired
            If `now` is at or after the plan's expiry.
        ConfirmationMismatch
            If the plan needs a phrase and `typed_confirmation` is not exactly it.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            raise PlanNotFound()
        if now >= plan.expires_at:
            del self._plans[plan_id]
            raise PlanExpired()
        if plan.confirm_phrase is not None and typed_confirmation != plan.confirm_phrase:
            raise ConfirmationMismatch()
        del self._plans[plan_id]
        return plan
