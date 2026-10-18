"""Italian texts and the per-step report of an executed action (spec 8.4, 10)."""

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

from wimm.i18n import N_, _, ngettext
from wimm.model.actions import Plan, ProcessFingerprint
from wimm.model.enums import ActionKind
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.format import format_size

# The toast names the subject and a fixed noun phrase, so no label needs gender agreement.
GENERIC_FAMILY = "generic"
NOTHING_DONE_TEXT = N_("Nessuna operazione eseguita")
FAMILY_TEXTS = MappingProxyType(
    {
        "stop": (N_("arresto completato"), N_("fermati"), N_("già chiuso")),
        "kill": (N_("chiusura forzata completata"), N_("chiusi a forza"), N_("già chiuso")),
        "remove": (N_("rimozione completata"), N_("rimossi"), N_("già rimosso")),
        "clean": (N_("pulizia completata"), N_("puliti"), N_("già pulito")),
        "start": (N_("riavvio completato"), N_("riavviati"), N_("già acceso")),
        GENERIC_FAMILY: (N_("operazione completata"), N_("completati"), N_("già a posto")),
    }
)
FAMILY_OF = MappingProxyType(
    {
        ActionKind.PROCESS_TERMINATE: "stop",
        ActionKind.APP_CLOSE: "stop",
        ActionKind.CONTAINER_STOP: "stop",
        ActionKind.GROUP_STOP: "stop",
        ActionKind.COMPOSE_DOWN: "stop",
        ActionKind.COMPOSE_DOWN_VOLUMES: "stop",
        ActionKind.PROCESS_KILL: "kill",
        ActionKind.CONTAINER_REMOVE: "remove",
        ActionKind.IMAGE_REMOVE: "remove",
        ActionKind.VOLUME_REMOVE: "remove",
        ActionKind.DEVDIR_DELETE: "remove",
        ActionKind.IMAGES_PRUNE_DANGLING: "clean",
        ActionKind.IMAGES_PRUNE_UNUSED: "clean",
        ActionKind.BUILDER_PRUNE: "clean",
        ActionKind.CONTAINERS_PRUNE_STOPPED: "clean",
        ActionKind.CACHE_CLEAN: "clean",
        ActionKind.TRASH_EMPTY: "clean",
        ActionKind.CONTAINER_START: "start",
    }
)
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


def _family_texts(*, plan: Plan | None) -> tuple[str, str, str]:
    """The (done, plural participle, already gone) phrases of the plan's one action family."""
    kinds = set() if plan is None else {step.kind for step in plan.steps}
    families = {FAMILY_OF.get(kind, GENERIC_FAMILY) for kind in kinds}
    return FAMILY_TEXTS[families.pop() if len(families) == 1 else GENERIC_FAMILY]


def _subject_text(*, plan: Plan | None, subject: str | None, count: int) -> str:
    if subject:
        return subject
    if plan is not None and len(plan.steps) == 1:
        return plan.steps[0].target_label
    return ngettext("{count} elemento", "{count} elementi", count).format(count=count)


def _partial_text(*, participle: str, ok: int, stuck: int, failed: int) -> str:
    total = ok + stuck + failed
    parts = [_("{ok} su {total} {done}").format(ok=ok, total=total, done=_(participle))]
    if stuck:
        text = ngettext("{count} non risponde", "{count} non rispondono", stuck)
        parts.append(text.format(count=stuck))
    if failed:
        text = ngettext("{count} non riuscito", "{count} non riusciti", failed)
        parts.append(text.format(count=failed))
    return ", ".join(parts)


def summary_text(
    *, outcomes: Sequence[StepOutcome], plan: Plan | None = None, subject: str | None = None
) -> str:
    """The toast sentence: what happened to whom, or how many worked out of how many."""
    total = len(outcomes)
    if total == 0:
        return _(NOTHING_DONE_TEXT)
    done, participle, gone = _family_texts(plan=plan)
    # ALREADY_GONE counts as reached: the target is where the user wanted it.
    ok = sum(1 for outcome in outcomes if outcome.status in OK_STATUSES)
    stuck = sum(1 for outcome in outcomes if outcome.status is StepStatus.NOT_RESPONDING)
    who = _subject_text(plan=plan, subject=subject, count=total)
    if ok == total:
        all_gone = all(outcome.status is StepStatus.ALREADY_GONE for outcome in outcomes)
        return _("{subject}: {done}").format(subject=who, done=_(gone if all_gone else done))
    if total == 1:
        problem = _("non risponde") if stuck else _("operazione non riuscita")
        return _("{subject}: {problem}").format(subject=who, problem=problem)
    return _partial_text(participle=participle, ok=ok, stuck=stuck, failed=total - ok - stuck)


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
