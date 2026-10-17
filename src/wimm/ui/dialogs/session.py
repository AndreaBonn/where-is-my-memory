"""State of one confirmation dialog: the current plan and the entries the user kept (Q-5)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from wimm.model.actions import (
    EXCLUDABLE_ACTIONS,
    ActionRequest,
    ContainerFingerprint,
    ImageFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind
from wimm.model.errors import InvalidRequest, WimmError
from wimm.model.snapshot import ContainerMember, Group, ProcessMember, Snapshot

LOGGER = logging.getLogger(__name__)
CHANGED_NOTICE = "La situazione è cambiata: chiudi e riapri per vedere l'elenco aggiornato."


@dataclass(frozen=True, slots=True)
class StepEntry:
    """One line of the dialog: the step label, the id that excludes it and its group."""

    step_id: str | None
    label: str
    group: str | None


def step_id_of(*, step: PlanStep) -> str | None:
    """The id `excluded_ids` uses for a step: the pid, container id or image id."""
    fingerprint = step.fingerprint
    if isinstance(fingerprint, ProcessFingerprint):
        return str(fingerprint.pid)
    if isinstance(fingerprint, ContainerFingerprint | ImageFingerprint):
        return fingerprint.id
    return None


def _group_names(*, snapshot: Snapshot | None) -> dict[str, str]:
    names: dict[str, str] = {}
    groups: tuple[Group, ...] = () if snapshot is None else snapshot.groups
    for group in groups:
        for member in group.members:
            if isinstance(member, ProcessMember):
                names[str(member.pid)] = group.name
            elif isinstance(member, ContainerMember):
                names[member.id] = group.name
    return names


def entries_for(*, plan: Plan, snapshot: Snapshot | None) -> tuple[StepEntry, ...]:
    """One entry per step of ``plan``, labelled with the group each member belongs to."""
    names = _group_names(snapshot=snapshot)
    entries = []
    for step in plan.steps:
        step_id = step_id_of(step=step)
        entries.append(
            StepEntry(step_id=step_id, label=step.target_label, group=names.get(step_id or ""))
        )
    return tuple(entries)


class ConfirmSession:
    """The plan being confirmed; removing an entry asks the service for a new plan."""

    def __init__(
        self,
        *,
        plan: Plan,
        subject: str | None,
        entries: tuple[StepEntry, ...],
        replan: Callable[[ActionRequest], Plan],
    ) -> None:
        self.kind = plan.request.kind
        self.subject = subject
        self.entries = entries
        self.plan: Plan | None = plan
        self.notice: str | None = None
        self._request = plan.request
        self._replan = replan
        self._excluded: frozenset[str] = frozenset()
        self.multiple = (
            plan.request.kind in EXCLUDABLE_ACTIONS
            and (plan.request.kind is ActionKind.STOP_ALL_IDLE_SAFE or len(plan.steps) > 1)
            and all(entry.step_id is not None for entry in entries)
        )

    def is_included(self, *, step_id: str) -> bool:
        """True while the entry is part of the request."""
        return step_id not in self._excluded

    def set_included(self, *, step_id: str, included: bool) -> None:
        """Include or exclude one entry and ask for the plan of what is left.

        With no entry left the plan is None and the dialog cannot be confirmed.
        """
        excluded = self._excluded - {step_id} if included else self._excluded | {step_id}
        self._excluded = excluded
        try:
            plan = self._replan(replace(self._request, excluded_ids=excluded))
        except InvalidRequest:
            self.plan, self.notice = None, None
            return
        except WimmError as error:
            LOGGER.warning("Plan refused after changing the entries: %s", error.message)
            self.plan, self.notice = None, error.user_message
            return
        # The service plans on the latest snapshot: a target the list never showed must not
        # be confirmed through it.
        if self._shows_every_step(plan=plan):
            self.plan, self.notice = plan, None
        else:
            self.plan, self.notice = None, CHANGED_NOTICE

    def _shows_every_step(self, *, plan: Plan) -> bool:
        shown = {entry.step_id for entry in self.entries}
        return all(step_id_of(step=step) in shown for step in plan.steps)
