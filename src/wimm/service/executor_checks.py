"""Execution-time revalidation of plan steps (SPECIFICHE 8.2). Pure given the controls."""

from dataclasses import dataclass

from wimm.core.assemble_members import STOPPABLE_STATES
from wimm.core.planning import cmdline_hash
from wimm.model.actions import ContainerFingerprint, PlanStep, ProcessFingerprint
from wimm.model.enums import ActionKind

from .control_protocols import DockerControl, LiveProcess, ProcessControl
from .errors import InvalidRequest, ProtectedTarget, TargetChanged
from .executor_compose import COMPOSE_KINDS
from .executor_disk_docker import DISK_DOCKER_KINDS
from .executor_disk_fs import DISK_FS_KINDS

PROCESS_KINDS = frozenset({ActionKind.PROCESS_TERMINATE, ActionKind.APP_CLOSE})
CONTAINER_KINDS = frozenset(
    {ActionKind.CONTAINER_STOP, ActionKind.CONTAINER_REMOVE, ActionKind.CONTAINER_START}
)
DOCKER_KINDS = CONTAINER_KINDS | DISK_DOCKER_KINDS
SUPPORTED_KINDS = PROCESS_KINDS | DOCKER_KINDS | COMPOSE_KINDS | DISK_FS_KINDS


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessRules:
    """What the executor knows about the caller: the user and wimm's own lineage."""

    owner_uid: int
    lineage: frozenset[int]


def check_supported(*, step: PlanStep) -> None:
    """Reject a step kind the executor does not execute, before anything is touched."""
    if step.kind not in SUPPORTED_KINDS:
        raise InvalidRequest(f"Executor does not support {step.kind.value}")


def _unchanged(*, fingerprint: ProcessFingerprint, live: LiveProcess) -> bool:
    return (
        live.create_time == fingerprint.create_time
        and live.uid == fingerprint.uid
        and cmdline_hash(cmdline=live.cmdline) == fingerprint.cmdline_hash
    )


def check_protection(*, live: LiveProcess, rules: ProcessRules) -> None:
    if live.uid != rules.owner_uid:
        raise ProtectedTarget(f"Process {live.pid} belongs to uid {live.uid}")
    if live.protected:
        raise ProtectedTarget(f"Process {live.pid} is in a protected category")
    if live.pid in rules.lineage:
        raise ProtectedTarget(f"Process {live.pid} is wimm or one of its ancestors")


def check_process(
    *, step: PlanStep, control: ProcessControl, rules: ProcessRules
) -> LiveProcess | None:
    """Return the live process for a step, None if gone; raise if it must not be touched.

    A PID reused by another process (different start time) is `TargetChanged`. The live
    uid is compared with the user, never with the fingerprint, and protection is
    re-evaluated even if the planner already excluded it.
    """
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ProcessFingerprint):
        raise InvalidRequest(f"Step {step.order} has no process fingerprint")
    live = control.inspect(pid=fingerprint.pid)
    if live is None:
        return None
    if live.create_time != fingerprint.create_time:
        raise TargetChanged(f"Process {fingerprint.pid} was replaced (start time changed)")
    check_protection(live=live, rules=rules)
    if not _unchanged(fingerprint=fingerprint, live=live):
        raise TargetChanged(f"Process {fingerprint.pid} changed since the plan was built")
    return live


def check_container(*, step: PlanStep, control: DockerControl) -> None:
    """Reject the plan if the container's state differs from the fingerprint; gone is fine."""
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ContainerFingerprint):
        raise InvalidRequest(f"Step {step.order} has no container fingerprint")
    live = control.inspect(container_id=fingerprint.id)
    if live is None or live.status == fingerprint.status:
        return
    # Stopped by the user in the meantime: the stop is already done (section 8.4 point 5).
    if step.kind is ActionKind.CONTAINER_STOP and live.status not in STOPPABLE_STATES:
        return
    # Started again by the user meanwhile: «Riaccendi» has nothing left to do (C4).
    if step.kind is ActionKind.CONTAINER_START and live.status in STOPPABLE_STATES:
        return
    raise TargetChanged(
        f"Container {fingerprint.id[:12]} is {live.status}, plan expected {fingerprint.status}"
    )
