"""C4: which containers each recent plan stopped, so «Riaccendi» can start them again."""

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from wimm.core.planning_restart import StoppedContainer, StoppedProcess, restart_command
from wimm.model.actions import ContainerFingerprint, Plan, ProcessFingerprint
from wimm.model.enums import ActionKind, PlanId
from wimm.model.snapshot import ProcessMember, Snapshot

from .control_protocols import StepOutcome, StepStatus

# The toast offering «Riaccendi» lasts seconds: a few plans back is plenty.
RECENT_PLANS = 8
# Plans seen but not (yet) run: a plan the user never confirms must not pile up commands.
NOTED_PLANS = 16
PROCESS_STOPS = frozenset(
    {ActionKind.PROCESS_TERMINATE, ActionKind.PROCESS_KILL, ActionKind.APP_CLOSE}
)


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


class StoppedProcesses:
    """F14: the command of each process a recent plan stopped. RAM only, never logged.

    The command is read from the snapshot the plan was built on (`note`), not from the
    latest one: the process is gone by the time anyone asks. A cmdline can hold secrets,
    so nothing here is written to disk or to a log, and a restart of wimm forgets it all.
    """

    def __init__(self) -> None:
        self._noted: OrderedDict[PlanId, dict[int, StoppedProcess]] = OrderedDict()
        self._stopped: OrderedDict[str, tuple[StoppedProcess, ...]] = OrderedDict()

    def note(self, *, plan: Plan, snapshot: Snapshot) -> None:
        """Keep argv, cwd and label of the processes `plan` is about to stop."""
        members = {
            (member.pid, member.create_time): member
            for group in snapshot.groups
            for member in group.members
            if isinstance(member, ProcessMember)
        }
        found: dict[int, StoppedProcess] = {}
        for step in plan.steps:
            fingerprint = step.fingerprint
            if step.kind not in PROCESS_STOPS or not isinstance(fingerprint, ProcessFingerprint):
                continue
            member = members.get((fingerprint.pid, fingerprint.create_time))
            if member is not None:
                found[step.order] = StoppedProcess(
                    label=step.target_label, argv=member.cmdline, cwd=member.cwd
                )
        if not found:
            return
        self._noted[plan.plan_id] = found
        while len(self._noted) > NOTED_PLANS:
            self._noted.popitem(last=False)

    def record(self, *, plan_id: PlanId, outcomes: Sequence[StepOutcome]) -> None:
        """Keep the noted processes whose stop finished; only the latest plans are kept."""
        found = self._noted.pop(plan_id, None)
        if found is None:
            return
        done = {outcome.order for outcome in outcomes if outcome.status is StepStatus.DONE}
        stopped = tuple(found[order] for order in sorted(found) if order in done)
        if not stopped:
            return
        self._stopped[plan_id] = stopped
        while len(self._stopped) > RECENT_PLANS:
            self._stopped.popitem(last=False)

    def commands(self, *, plan_id: PlanId) -> tuple[str, ...]:
        """One restart command per stopped process that has a safe one, in plan order."""
        commands = (
            restart_command(argv=item.argv, cwd=item.cwd) for item in self._stopped.get(plan_id, ())
        )
        return tuple(command for command in commands if command is not None)

    @property
    def stopped(self) -> Mapping[str, tuple[StoppedProcess, ...]]:
        """A read-only copy, by plan id."""
        return MappingProxyType(dict(self._stopped))


class RestartMemory:
    """What the service remembers to restart after a stop: containers and process commands."""

    def __init__(self) -> None:
        self._containers = StoppedContainers()
        self._processes = StoppedProcesses()

    def note(self, *, plan: Plan, snapshot: Snapshot) -> None:
        """At planning time: keep the commands of the processes the plan would stop."""
        self._processes.note(plan=plan, snapshot=snapshot)

    def track(self, *, plan: Plan) -> None:
        """A plan is about to run."""
        self._containers.track(plan=plan)

    def record(self, *, plan_id: PlanId, outcomes: Sequence[StepOutcome]) -> None:
        """A plan finished (no outcomes: it did not run)."""
        self._containers.record(plan_id=plan_id, outcomes=outcomes)
        self._processes.record(plan_id=plan_id, outcomes=outcomes)

    def commands(self, *, plan_id: PlanId) -> tuple[str, ...]:
        """The restart commands of the processes `plan_id` stopped."""
        return self._processes.commands(plan_id=plan_id)

    @property
    def stopped(self) -> Mapping[str, tuple[StoppedContainer, ...]]:
        """The containers recent plans stopped, by plan id."""
        return self._containers.stopped
