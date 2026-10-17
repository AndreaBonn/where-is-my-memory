import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import partial
from typing import Any, Protocol

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, PlanId, TargetId
from wimm.model.errors import InvalidRequest, WimmError
from wimm.model.snapshot import Snapshot
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.errors import PlanExpired, TargetChanged
from wimm.ui.dialogs.confirm import ConfirmDialog
from wimm.ui.dialogs.outcome import OutcomeDialog
from wimm.ui.dialogs.session import ConfirmSession, entries_for
from wimm.ui.outcome import (
    OK_STATUSES,
    StepReport,
    freed_text,
    outcomes_freed_text,
    step_reports,
    summary_text,
)

LOGGER = logging.getLogger(__name__)
NOTHING_TO_STOP_TEXT = "Non c'è niente da fermare senza rischi"
NOTHING_SAFE_ON_DISK_TEXT = "Non c'è niente da liberare senza rischi sul disco"
# The invalid requests the UI builds itself: "everything safe" with nothing left to do.
NOTHING_LEFT_TEXTS = {
    ActionKind.STOP_ALL_IDLE_SAFE: NOTHING_TO_STOP_TEXT,
    ActionKind.DISK_FREE_SAFE: NOTHING_SAFE_ON_DISK_TEXT,
}
REPLAN_TEXT = "La situazione è cambiata, ricalcolo…"
DETAILS_LABEL = "Dettagli"
RESTART_LABEL = "Riaccendi"
REPLANNED_ERRORS = (PlanExpired, TargetChanged)


class ActionSource(Protocol):
    """What the flow needs from the service; ``AppService`` satisfies it."""

    def snapshot(self) -> Snapshot | None: ...

    def plan(self, *, request: ActionRequest) -> Plan: ...

    def execute(self, *, plan_id: PlanId, typed_confirmation: str | None) -> None: ...

    def connect(self, detailed_signal: str, handler: Callable[..., Any], *args: Any) -> int: ...

    def disconnect(self, handler_id: int) -> None: ...


class Notifier(Protocol):
    """Shows a message; with ``button`` the message carries an action."""

    def __call__(
        self, text: str, *, button: str | None = None, on_button: Callable[[], None] | None = None
    ) -> None: ...


def can_act(*, source: object) -> bool:
    """True when the source can plan actions (the real service; the test sources cannot)."""
    return callable(getattr(source, "plan", None))


@dataclass(frozen=True, slots=True)
class _Pending:
    """A confirmed plan waiting for its outcome; ``may_replan`` allows one fresh plan."""

    plan: Plan
    subject: str | None
    may_replan: bool


@dataclass(frozen=True, slots=True)
class _Report:
    """The last finished action: what the details show and what it freed."""

    plan_id: PlanId
    summary: str
    steps: tuple[StepReport, ...]
    freed: str | None = None
    restartable: bool = False


class ActionFlow:
    """Button click -> plan -> confirmation -> execute -> outcome toast, details, force-kill."""

    def __init__(
        self,
        *,
        source: ActionSource,
        parent: Gtk.Widget,
        notify: Notifier,
        on_busy: Callable[[bool], None],
    ) -> None:
        self._source = source
        self._parent = parent
        self._notify = notify
        self._on_busy = on_busy
        self.dialog: ConfirmDialog | None = None
        self.details: OutcomeDialog | None = None
        self._pending: dict[str, _Pending] = {}
        self._report: _Report | None = None
        self._handlers = [
            source.connect("action-finished", self._on_finished),
            source.connect("action-rejected", self._on_rejected),
            source.connect("reclaim-measured", self._on_reclaim),
        ]

    def start(self, *, request: ActionRequest, subject: str | None) -> None:
        """Plan ``request`` and ask the user; a refused plan shows its message, no dialog."""
        self._begin(request=request, subject=subject, may_replan=True)

    def close(self) -> None:
        """Disconnect from the service, which outlives the window."""
        for handler in self._handlers:
            self._source.disconnect(handler)
        self._handlers = []

    def _begin(self, *, request: ActionRequest, subject: str | None, may_replan: bool) -> None:
        try:
            plan = self._source.plan(request=request)
        except InvalidRequest as error:
            self._notify(NOTHING_LEFT_TEXTS.get(request.kind, error.user_message))
            return
        except WimmError as error:
            self._notify(error.user_message)
            return
        session = ConfirmSession(
            plan=plan,
            subject=subject,
            entries=entries_for(plan=plan, snapshot=self._source.snapshot()),
            replan=lambda new: self._source.plan(request=new),
        )
        dialog = ConfirmDialog(
            session=session,
            snapshot=self._source.snapshot(),
            on_confirm=lambda confirmed, typed: self._confirm(
                _Pending(plan=confirmed, subject=subject, may_replan=may_replan), typed
            ),
        )
        dialog.connect("closed", self._on_closed)
        self.dialog = dialog
        dialog.present(self._parent)

    def _confirm(self, pending: _Pending, typed: str | None) -> None:
        plan_id = pending.plan.plan_id
        self._pending[plan_id] = pending
        self._on_busy(True)
        try:
            self._source.execute(plan_id=plan_id, typed_confirmation=typed)
        except WimmError as error:
            self._reject(plan_id=plan_id, error=error)
        except Exception:
            # Anything else would leave every action button "In corso…" for good.
            LOGGER.exception("Executing plan %s failed", plan_id)
            self._reject(plan_id=plan_id, error=WimmError())

    def _on_closed(self, *_args: object) -> None:
        self.dialog = None

    def _release(self, *, plan_id: str) -> _Pending | None:
        """Forget a plan that has an outcome and enable the buttons if none is left."""
        pending = self._pending.pop(plan_id, None)
        if pending is not None:
            self._on_busy(bool(self._pending))
        return pending

    def _on_finished(self, _source: object, plan_id: str, outcomes: Sequence[StepOutcome]) -> None:
        pending = self._release(plan_id=plan_id)
        plan = None if pending is None else pending.plan
        steps = step_reports(plan=plan, outcomes=outcomes)
        self._report = _Report(
            plan_id=PlanId(plan_id),
            summary=summary_text(outcomes=outcomes),
            steps=steps,
            freed=outcomes_freed_text(outcomes=outcomes),
            restartable=_stopped_containers(plan=plan, outcomes=outcomes),
        )
        self._announce()

    def _announce(self) -> None:
        report = self._report
        if report is None:
            return
        text = report.summary if report.freed is None else f"{report.summary}. {report.freed}"
        # SPECIFICHE 10.3: the details are offered only when some target did not succeed.
        if not all(step.status in OK_STATUSES for step in report.steps):
            self._notify(text, button=DETAILS_LABEL, on_button=self._show_details)
        elif report.restartable:
            restart = partial(self._restart, plan_id=report.plan_id)
            self._notify(text, button=RESTART_LABEL, on_button=restart)
        else:
            self._notify(text)

    def _restart(self, *, plan_id: PlanId) -> None:
        """C4: plan the start of what ``plan_id`` stopped; the user confirms it as usual."""
        target = TargetId(plan_id)
        self.start(
            request=ActionRequest(kind=ActionKind.RESTART_STOPPED, target_id=target), subject=None
        )

    def _on_reclaim(self, _source: object, plan_id: str, delta: ReclaimDelta) -> None:
        report = self._report
        text = freed_text(delta=delta)
        if report is None or report.plan_id != plan_id or text is None:
            return
        self._report = replace(report, freed=text)
        if self.details is not None:
            self.details.set_freed(text=text)
        self._announce()

    def _show_details(self) -> None:
        report = self._report
        if report is None:
            return
        dialog = OutcomeDialog(reports=report.steps, on_force=self._force_close)
        dialog.set_freed(text=report.freed)
        dialog.connect("closed", lambda *_args: setattr(self, "details", None))
        self.details = dialog
        dialog.present(self._parent)

    def _force_close(self, report: StepReport) -> None:
        """Ask for a NEW process_kill plan: the user confirms it like any other action."""
        if self.details is not None:
            self.details.force_close()
        request = ActionRequest(kind=ActionKind.PROCESS_KILL, target_id=TargetId(str(report.pid)))
        self.start(request=request, subject=report.label)

    def _on_rejected(self, _source: object, plan_id: str, error: WimmError) -> None:
        self._reject(plan_id=plan_id, error=error)

    def _reject(self, *, plan_id: str, error: WimmError) -> None:
        pending = self._release(plan_id=plan_id)
        if pending is not None and _should_replan(pending=pending, error=error):
            self._notify(REPLAN_TEXT)
            self._begin(request=pending.plan.request, subject=pending.subject, may_replan=False)
            return
        self._notify(error.user_message)


def _stopped_containers(*, plan: Plan | None, outcomes: Sequence[StepOutcome]) -> bool:
    """True when the plan stopped at least one container: those can be started again."""
    done = {outcome.order for outcome in outcomes if outcome.status is StepStatus.DONE}
    steps = () if plan is None else plan.steps
    return any(s.kind is ActionKind.CONTAINER_STOP and s.order in done for s in steps)


def _should_replan(*, pending: "_Pending", error: WimmError) -> bool:
    """Replan once after an expiry or a change, never on the same pid after a change.

    A changed single target is a replaced process: planning its pid again could aim at
    another program, so the user gets the message instead.
    """
    if not pending.may_replan or not isinstance(error, REPLANNED_ERRORS):
        return False
    return not (isinstance(error, TargetChanged) and pending.plan.request.target_id is not None)
