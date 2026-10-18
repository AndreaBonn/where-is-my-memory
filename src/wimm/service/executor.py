"""Executes a confirmed plan (SPECIFICHE 8.2, 8.4). Revalidates first, then acts."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from itertools import groupby

from wimm.config import Config
from wimm.core.constants import CONTAINER_STOP_WORKERS, TERMINATE_TIMEOUT_S
from wimm.model.actions import Plan, PlanStep, ProcessFingerprint
from wimm.model.enums import ActionKind

from .control_protocols import (
    ComposeControl,
    DockerControl,
    ProcessControl,
    StepOutcome,
    StepStatus,
    failed_outcome,
)
from .errors import DockerUnavailable, InvalidRequest
from .executor_checks import (
    DOCKER_KINDS,
    ENGINE_KINDS,
    PROCESS_KINDS,
    ProcessRules,
    check_container,
    check_engines,
    check_process,
    check_supported,
)
from .executor_compose import COMPOSE_KINDS, check_compose, run_compose_step
from .executor_disk_docker import (
    DISK_DOCKER_KINDS,
    check_disk_docker,
    log_disk_outcomes,
    run_disk_docker_step,
)
from .executor_disk_fs import DISK_FS_KINDS, check_disk_fs, run_disk_fs_step
from .executor_docker import run_container_step
from .executor_process import TerminationRequest, close_root, terminate_tree
from .fs_controls import DiskFsControl


@dataclass(slots=True, kw_only=True)
class PlanExecutor:
    """Run a plan whose confirmation was already verified by the service.

    Every step is revalidated against the live system before any step acts: a changed
    or protected target rejects the whole plan. Steps then run in plan order, each
    yielding an outcome; consecutive container stops run in parallel.
    """

    processes: ProcessControl
    containers: DockerControl | None
    owner_uid: int
    compose: ComposeControl | None = None
    disk_fs: DiskFsControl | None = None
    terminate_timeout_s: float = TERMINATE_TIMEOUT_S

    def apply_config(self, *, config: Config) -> None:
        """Adopt the terminate timeout, protected names and SSH option of a new configuration.

        Called on the worker that runs plans, so it never lands in the middle of one.
        """
        self.terminate_timeout_s = config.terminate_timeout_s
        self.processes.set_extra_protected_names(names=config.extra_protected_names)
        self.processes.set_remote_sessions_actionable(enabled=config.remote_sessions_actionable)
        if self.disk_fs is not None:
            self.disk_fs = replace(
                self.disk_fs, roots=config.admitted_roots, min_age_days=config.devdirs_min_age_days
            )

    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        rules = ProcessRules(owner_uid=self.owner_uid, lineage=self.processes.self_lineage())
        self._revalidate(plan=plan, rules=rules)
        outcomes: list[StepOutcome] = []
        for _, run in groupby(plan.steps, key=lambda step: step.kind):
            batch = self._run_batch(steps=tuple(run), rules=rules)
            outcomes.extend(batch)
            log_disk_outcomes(plan=plan, outcomes=batch)
        return tuple(outcomes)

    def _revalidate(self, *, plan: Plan, rules: ProcessRules) -> None:
        """Check every step against the live system; any change rejects the whole plan."""
        for step in plan.steps:
            check_supported(step=step)
        containers = self.containers
        if containers is None and any(s.kind in DOCKER_KINDS for s in plan.steps):
            raise DockerUnavailable()
        compose = self.compose
        if compose is None and any(s.kind in COMPOSE_KINDS for s in plan.steps):
            raise DockerUnavailable()
        disk_fs = self.disk_fs
        if disk_fs is None and any(s.kind in DISK_FS_KINDS for s in plan.steps):
            raise InvalidRequest("Folder, cache and trash actions are not available")
        if any(s.kind in ENGINE_KINDS for s in plan.steps):
            source = containers or compose
            if source is not None:
                check_engines(plan=plan, live=source.engine_identities())
        for step in plan.steps:
            if step.kind in PROCESS_KINDS:
                check_process(step=step, control=self.processes, rules=rules)
            elif step.kind in COMPOSE_KINDS and compose is not None:
                check_compose(step=step, control=compose)
            elif disk_fs is not None and step.kind in DISK_FS_KINDS:
                check_disk_fs(step=step, control=disk_fs)
            elif containers is not None and step.kind in DISK_DOCKER_KINDS:
                check_disk_docker(step=step, control=containers)
            elif containers is not None:
                check_container(step=step, control=containers)

    def _run_batch(self, *, steps: tuple[PlanStep, ...], rules: ProcessRules) -> list[StepOutcome]:
        if steps[0].kind in PROCESS_KINDS:
            return [self._terminate(step=s, rules=rules) for s in steps]
        if steps[0].kind in COMPOSE_KINDS:
            return self._run_compose(steps=steps)
        if steps[0].kind in DISK_DOCKER_KINDS:
            return self._run_disk_docker(steps=steps)
        if steps[0].kind in DISK_FS_KINDS:
            return self._run_disk_fs(steps=steps)
        if steps[0].kind is ActionKind.CONTAINER_STOP:
            return self._run_containers(steps=steps, parallel=True)
        return self._run_containers(steps=steps, parallel=False)

    def _run_compose(self, *, steps: tuple[PlanStep, ...]) -> list[StepOutcome]:
        control = self.compose
        if control is None:
            raise DockerUnavailable()
        return [run_compose_step(control=control, step=s) for s in steps]

    def _run_disk_docker(self, *, steps: tuple[PlanStep, ...]) -> list[StepOutcome]:
        control = self.containers
        if control is None:
            raise DockerUnavailable()
        return [run_disk_docker_step(control=control, step=s) for s in steps]

    def _run_disk_fs(self, *, steps: tuple[PlanStep, ...]) -> list[StepOutcome]:
        control = self.disk_fs
        if control is None:
            raise InvalidRequest("Folder, cache and trash actions are not available")
        return [run_disk_fs_step(control=control, step=s) for s in steps]

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
            stop = close_root if step.kind is ActionKind.APP_CLOSE else terminate_tree
            return stop(control=self.processes, request=request)
        except Exception as error:
            return failed_outcome(order=step.order, error=error)
