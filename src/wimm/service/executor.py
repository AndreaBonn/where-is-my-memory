"""Executes a confirmed plan (SPECIFICHE 8.2, 8.4). Revalidates first, then acts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import groupby

from wimm.core.constants import CONTAINER_STOP_WORKERS, TERMINATE_TIMEOUT_S
from wimm.model.actions import Plan, PlanStep, ProcessFingerprint
from wimm.model.enums import ActionKind

from .control_protocols import (
    DockerControl,
    ProcessControl,
    StepOutcome,
    StepStatus,
)
from .errors import DockerUnavailable, InvalidRequest, WimmError
from .executor_checks import (
    CONTAINER_KINDS,
    PROCESS_KINDS,
    ProcessRules,
    check_container,
    check_process,
    check_supported,
)
from .executor_docker import run_container_step
from .executor_process import TerminationRequest, terminate_tree


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanExecutor:
    """Run a plan whose confirmation was already verified by the service.

    Every step is revalidated against the live system before any step acts: a changed
    or protected target rejects the whole plan. Steps then run in plan order, each
    yielding an outcome; consecutive container stops run in parallel.
    """

    processes: ProcessControl
    containers: DockerControl | None
    owner_uid: int
    terminate_timeout_s: float = TERMINATE_TIMEOUT_S

    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        rules = ProcessRules(owner_uid=self.owner_uid, lineage=self.processes.self_lineage())
        self._revalidate(plan=plan, rules=rules)
        outcomes: list[StepOutcome] = []
        for _, run in groupby(plan.steps, key=lambda step: step.kind):
            outcomes.extend(self._run_batch(steps=tuple(run), rules=rules))
        return tuple(outcomes)

    def _revalidate(self, *, plan: Plan, rules: ProcessRules) -> None:
        """Check every step against the live system; any change rejects the whole plan."""
        for step in plan.steps:
            check_supported(step=step)
        containers = self.containers
        if containers is None and any(s.kind in CONTAINER_KINDS for s in plan.steps):
            raise DockerUnavailable()
        for step in plan.steps:
            if step.kind in PROCESS_KINDS:
                check_process(step=step, control=self.processes, rules=rules)
            elif containers is not None:
                check_container(step=step, control=containers)

    def _run_batch(self, *, steps: tuple[PlanStep, ...], rules: ProcessRules) -> list[StepOutcome]:
        if steps[0].kind in PROCESS_KINDS:
            return [self._terminate(step=s, rules=rules) for s in steps]
        if steps[0].kind is ActionKind.CONTAINER_STOP:
            return self._run_containers(steps=steps, parallel=True)
        return self._run_containers(steps=steps, parallel=False)

    def _run_containers(self, *, steps: tuple[PlanStep, ...], parallel: bool) -> list[StepOutcome]:
        control = self.containers
        if control is None:
            raise DockerUnavailable()
        if not parallel:
            return [run_container_step(control=control, step=s) for s in steps]
        workers = min(len(steps), CONTAINER_STOP_WORKERS)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(lambda s: run_container_step(control=control, step=s), steps))

    def _terminate(self, *, step: PlanStep, rules: ProcessRules) -> StepOutcome:
        """Recheck the root right before acting; a failure here fails only this step."""
        fingerprint = step.fingerprint
        if not isinstance(fingerprint, ProcessFingerprint):
            raise InvalidRequest(f"Step {step.order} has no process fingerprint")
        request = TerminationRequest(
            order=step.order, pid=fingerprint.pid, timeout_s=self.terminate_timeout_s, rules=rules
        )
        try:
            live = check_process(step=step, control=self.processes, rules=rules)
            if live is None:
                return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
            return terminate_tree(control=self.processes, request=request)
        except WimmError as error:
            return StepOutcome(order=step.order, status=StepStatus.FAILED, message=error.message)
