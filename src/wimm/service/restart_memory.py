"""C4: which containers each recent plan stopped, so «Riaccendi» can start them again."""

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from wimm.core.planning_restart import StoppedContainer
from wimm.model.actions import ContainerFingerprint, Plan
from wimm.model.enums import ActionKind, PlanId

from .control_protocols import StepOutcome, StepStatus

# The toast offering «Riaccendi» lasts seconds: a few plans back is plenty.
RECENT_PLANS = 8


class StoppedContainers:
    """Plans in flight and, once they finish, the containers they really stopped."""

    def __init__(self) -> None:
        self._running: dict[PlanId, Plan] = {}
        self._stopped: OrderedDict[str, tuple[StoppedContainer, ...]] = OrderedDict()

    def track(self, *, plan: Plan) -> None:
        """Remember a plan that is about to run."""
        self._running[plan.plan_id] = plan

    def record(self, *, plan_id: PlanId, outcomes: Sequence[StepOutcome]) -> None:
        """Keep the containers whose stop finished; only the latest plans are kept.

        A plan that did not run is recorded with no outcomes, so it is dropped.
        """
        plan = self._running.pop(plan_id, None)
        if plan is None:
            return
        done = {outcome.order for outcome in outcomes if outcome.status is StepStatus.DONE}
        stopped = tuple(
            StoppedContainer(id=step.fingerprint.id, label=step.target_label)
            for step in plan.steps
            if step.kind is ActionKind.CONTAINER_STOP
            and step.order in done
            and isinstance(step.fingerprint, ContainerFingerprint)
        )
        if not stopped:
            return
        self._stopped[plan_id] = stopped
        while len(self._stopped) > RECENT_PLANS:
            self._stopped.popitem(last=False)

    @property
    def stopped(self) -> Mapping[str, tuple[StoppedContainer, ...]]:
        """A read-only copy, by plan id."""
        return MappingProxyType(dict(self._stopped))
