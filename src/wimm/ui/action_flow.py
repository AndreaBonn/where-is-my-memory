import logging
from collections.abc import Callable
from typing import Any, Protocol

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, PlanId
from wimm.model.errors import InvalidRequest, WimmError
from wimm.model.snapshot import Snapshot
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.dialogs.confirm import ConfirmDialog
from wimm.ui.dialogs.session import ConfirmSession, entries_for

LOGGER = logging.getLogger(__name__)
DONE_TEXT = "Fatto"
PARTIAL_TEXT = "Alcune operazioni non sono riuscite"
NOTHING_TO_STOP_TEXT = "Non c'è nessun gruppo inattivo e sicuro da fermare"
OK_STATUSES = frozenset({StepStatus.DONE, StepStatus.ALREADY_GONE})


class ActionSource(Protocol):
    """What the flow needs from the service; ``AppService`` satisfies it."""

    def snapshot(self) -> Snapshot | None: ...

    def plan(self, *, request: ActionRequest) -> Plan: ...

    def execute(self, *, plan_id: PlanId, typed_confirmation: str | None) -> None: ...

    def connect(self, detailed_signal: str, handler: Callable[..., Any], *args: Any) -> int: ...

    def disconnect(self, handler_id: int) -> None: ...


def can_act(*, source: object) -> bool:
    """True when the source can plan actions (the real service; the test sources cannot)."""
    return callable(getattr(source, "plan", None))


class ActionFlow:
    """Button click -> plan -> confirmation dialog -> execute, with a minimal outcome message."""

    def __init__(
        self, *, source: ActionSource, parent: Gtk.Widget, notify: Callable[[str], None]
    ) -> None:
        self._source = source
        self._parent = parent
        self._notify = notify
        self.dialog: ConfirmDialog | None = None
        self._handlers = [
            source.connect("action-finished", self._on_finished),
            source.connect("action-rejected", self._on_rejected),
        ]

    def start(self, *, request: ActionRequest, subject: str | None) -> None:
        """Plan ``request`` and ask the user; a refused plan shows its message, no dialog."""
        try:
            plan = self._source.plan(request=request)
        except InvalidRequest as error:
            # The only invalid request the UI builds itself is stop-all with nothing left.
            nothing = request.kind is ActionKind.STOP_ALL_IDLE_SAFE
            self._notify(NOTHING_TO_STOP_TEXT if nothing else error.user_message)
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
        dialog = ConfirmDialog(session=session, on_confirm=self._confirm)
        dialog.connect("closed", self._on_closed)
        self.dialog = dialog
        dialog.present(self._parent)

    def close(self) -> None:
        """Disconnect from the service, which outlives the window."""
        for handler in self._handlers:
            self._source.disconnect(handler)
        self._handlers = []

    def _confirm(self, plan: Plan, typed: str | None) -> None:
        try:
            self._source.execute(plan_id=plan.plan_id, typed_confirmation=typed)
        except WimmError as error:
            self._notify(error.user_message)

    def _on_closed(self, *_args: object) -> None:
        self.dialog = None

    def _on_finished(
        self, _source: object, _plan_id: str, outcomes: tuple[StepOutcome, ...]
    ) -> None:
        ok = all(outcome.status in OK_STATUSES for outcome in outcomes)
        self._notify(DONE_TEXT if ok else PARTIAL_TEXT)

    def _on_rejected(self, _source: object, _plan_id: str, error: WimmError) -> None:
        self._notify(error.user_message)
