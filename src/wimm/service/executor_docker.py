"""Container steps (SPECIFICHE 8.2, 8.4): stop with a timeout, remove only when stopped."""

from wimm.core.assemble_members import STOPPABLE_STATES
from wimm.core.constants import CONTAINER_STOP_TIMEOUT_S
from wimm.model.actions import ContainerFingerprint, PlanStep
from wimm.model.enums import ActionKind

from .control_protocols import DockerControl, LiveContainer, StepOutcome, StepStatus
from .errors import ControlFailed, InvalidRequest


def _container_id(*, step: PlanStep) -> str:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ContainerFingerprint):
        raise InvalidRequest(f"Step {step.order} has no container fingerprint")
    return fingerprint.id


def _stop(*, control: DockerControl, step: PlanStep, live: LiveContainer) -> StepOutcome:
    if live.status not in STOPPABLE_STATES:
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    control.stop(container_id=live.id, timeout_s=CONTAINER_STOP_TIMEOUT_S)
    return StepOutcome(order=step.order, status=StepStatus.DONE)


def _remove(*, control: DockerControl, step: PlanStep, live: LiveContainer) -> StepOutcome:
    if live.status in STOPPABLE_STATES:
        message = f"container is {live.status}: stop it before removing"
        return StepOutcome(order=step.order, status=StepStatus.FAILED, message=message)
    control.remove(container_id=live.id, volumes=False)
    return StepOutcome(order=step.order, status=StepStatus.DONE)


def run_container_step(*, control: DockerControl, step: PlanStep) -> StepOutcome:
    """Execute one container step against the container's state right now.

    The state is read again here rather than trusted from the plan, so a stop that ran
    earlier in the same plan makes the following remove legitimate, and a remove of a
    running container is refused with no call to Docker. Volumes are never removed.
    """
    try:
        live = control.inspect(container_id=_container_id(step=step))
        if live is None:
            return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
        if step.kind is ActionKind.CONTAINER_STOP:
            return _stop(control=control, step=step, live=live)
        return _remove(control=control, step=step, live=live)
    except ControlFailed as error:
        return StepOutcome(order=step.order, status=StepStatus.FAILED, message=error.message)
