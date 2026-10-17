"""Italian texts and the per-step report of an executed action (spec 8.4, 10)."""

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

from wimm.i18n import N_, _
from wimm.model.actions import Plan, ProcessFingerprint
from wimm.model.enums import ActionKind
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.format import format_size

DONE_TEXT = N_("Fatto")
PARTIAL_TEXT = N_("Alcune operazioni non sono riuscite")
NOT_RESPONDING_TEXT = N_("Un processo non ha risposto alla chiusura")
STEP_FALLBACK = N_("Passo {order}")
STATUS_TEXTS = MappingProxyType(
    {
        StepStatus.DONE: N_("Chiuso"),
        StepStatus.ALREADY_GONE: N_("Già chiuso"),
        StepStatus.NOT_RESPONDING: N_("Non risponde"),
        StepStatus.FAILED: N_("Non riuscito"),
    }
)
# C4: a start is the opposite of a stop, and reads that way.
START_STATUS_TEXTS = MappingProxyType(
    {**STATUS_TEXTS, StepStatus.DONE: N_("Riacceso"), StepStatus.ALREADY_GONE: N_("Già acceso")}
)
OK_STATUSES = frozenset({StepStatus.DONE, StepStatus.ALREADY_GONE})


@dataclass(frozen=True, slots=True)
class StepReport:
    """One line of the details: the target, how the step ended and the pid to force-close."""

    label: str
    status: StepStatus
    pid: int | None
    started: bool = False

    @property
    def status_text(self) -> str:
        """The status in the active language."""
        return _((START_STATUS_TEXTS if self.started else STATUS_TEXTS)[self.status])

    @property
    def can_force(self) -> bool:
        """True when a new process_kill plan can be asked for this step."""
        return self.status is StepStatus.NOT_RESPONDING and self.pid is not None


def step_reports(*, plan: Plan | None, outcomes: Sequence[StepOutcome]) -> tuple[StepReport, ...]:
    """Pair each outcome with its plan step; without the plan the label is generic."""
    steps = {} if plan is None else {step.order: step for step in plan.steps}
    reports = []
    for outcome in outcomes:
        step = steps.get(outcome.order)
        pid = None
        if step is not None and isinstance(step.fingerprint, ProcessFingerprint):
            pid = step.fingerprint.pid
        label = _(STEP_FALLBACK).format(order=outcome.order) if step is None else step.target_label
        started = step is not None and step.kind is ActionKind.CONTAINER_START
        reports.append(StepReport(label=label, status=outcome.status, pid=pid, started=started))
    return tuple(reports)


def summary_text(*, outcomes: Sequence[StepOutcome]) -> str:
    """The toast sentence: done, a process that does not answer, or a partial failure."""
    statuses = {outcome.status for outcome in outcomes}
    if StepStatus.NOT_RESPONDING in statuses:
        return _(NOT_RESPONDING_TEXT)
    return _(DONE_TEXT) if statuses <= OK_STATUSES else _(PARTIAL_TEXT)


def outcomes_freed_text(*, outcomes: Sequence[StepOutcome]) -> str | None:
    """ "Liberati 120 MB di disco" from the sizes the executor reported; None when none did."""
    total = sum(outcome.freed_bytes or 0 for outcome in outcomes)
    return _("Liberati {size} di disco").format(size=format_size(size=total)) if total > 0 else None


def freed_text(*, delta: ReclaimDelta) -> str | None:
    """ "Liberati 1,1 GB di RAM"; None when the measure shows nothing freed."""
    ram = format_size(size=delta.freed_ram) if delta.freed_ram > 0 else ""
    disk = format_size(size=delta.freed_disk) if delta.freed_disk > 0 else ""
    if ram and disk:
        return _("Liberati {ram} di RAM e {disk} di disco").format(ram=ram, disk=disk)
    if ram:
        return _("Liberati {size} di RAM").format(size=ram)
    if disk:
        return _("Liberati {size} di disco").format(size=disk)
    return None
