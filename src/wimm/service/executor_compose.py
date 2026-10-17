"""Compose project steps (SPECIFICHE 7.3, 8.2): same container set, then `down`."""

from wimm.model.actions import ComposeFingerprint, PlanStep
from wimm.model.enums import ActionKind

from .control_protocols import ComposeControl, StepOutcome, StepStatus, failed_outcome
from .errors import InvalidRequest, TargetChanged

COMPOSE_KINDS = frozenset({ActionKind.COMPOSE_DOWN, ActionKind.COMPOSE_DOWN_VOLUMES})


def _fingerprint(*, step: PlanStep) -> ComposeFingerprint:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ComposeFingerprint):
        raise InvalidRequest(f"Step {step.order} has no compose fingerprint")
    return fingerprint


def _live_ids(*, step: PlanStep, control: ComposeControl) -> frozenset[str]:
    """Return the project's live container ids; raise if they differ from the plan.

    An empty project is not a change: the plan was built from a project with containers
    (`compose_draft` refuses one without), so an empty set means someone removed them since,
    which is what `down` would have done: the step reports `ALREADY_GONE`.
    """
    fingerprint = _fingerprint(step=step)
    live = control.container_ids(project=fingerprint.project)
    if live and live != fingerprint.container_ids:
        raise TargetChanged(f"Compose project {fingerprint.project} changed since the plan")
    return live


def check_compose(*, step: PlanStep, control: ComposeControl) -> None:
    """Reject the plan if the project's container set differs from the fingerprint."""
    _live_ids(step=step, control=control)


def run_compose_step(*, control: ComposeControl, step: PlanStep) -> StepOutcome:
    """Take the project down, comparing its container set again right before acting."""
    try:
        if not _live_ids(step=step, control=control):
            return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
        volumes = step.kind is ActionKind.COMPOSE_DOWN_VOLUMES
        control.down(project=_fingerprint(step=step).project, volumes=volumes)
        return StepOutcome(order=step.order, status=StepStatus.DONE)
    except Exception as error:
        return failed_outcome(order=step.order, error=error)
