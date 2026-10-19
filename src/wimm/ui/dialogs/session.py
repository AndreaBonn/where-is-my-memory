"""State of one confirmation dialog: the current plan and the entries the user kept (Q-5)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from wimm.core.planning_disk import BUILD_CACHE_ID
from wimm.i18n import N_, _
from wimm.model.actions import (
    EXCLUDABLE_ACTIONS,
    ActionRequest,
    ContainerFingerprint,
    DirFingerprint,
    ImageFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind
from wimm.model.errors import InvalidRequest, WimmError
from wimm.model.snapshot import ContainerMember, Group, Member, ProcessMember, Snapshot
from wimm.ui.dialogs.facts import entry_label, members_by_id
from wimm.ui.format import RISK_TEXT

LOGGER = logging.getLogger(__name__)
CHANGED_NOTICE = N_("La situazione è cambiata: chiudi e riapri per vedere l'elenco aggiornato.")


@dataclass(frozen=True, slots=True)
class StepEntry:
    """One line of the dialog: the step label, the id that excludes it and its group."""

    step_id: str | None
    label: str
    group: str | None


def step_id_of(*, step: PlanStep) -> str | None:
    """The id `excluded_ids` uses for a step: pid, container or image id, folder, build cache."""
    fingerprint = step.fingerprint
    if isinstance(fingerprint, ProcessFingerprint):
        return str(fingerprint.pid)
    if isinstance(fingerprint, ContainerFingerprint | ImageFingerprint):
        return fingerprint.id
    if isinstance(fingerprint, DirFingerprint):
        return fingerprint.realpath
    return BUILD_CACHE_ID if step.kind is ActionKind.BUILDER_PRUNE else None


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


def _selected_entries(*, plan: Plan, members: dict[str, Member]) -> tuple[StepEntry, ...]:
    """S16: the steps of a selection by risk class, safest first, each one a removable entry.

    The planner makes one step per ticked row, in the order of the sorted ids: the id of
    the row is what the replan drops. If the two counts differ no entry can be removed.
    """
    ids = sorted(plan.request.selected_ids)
    aligned = len(ids) == len(plan.steps)
    ranked = [
        (
            step.risk,
            StepEntry(
                step_id=ids[index] if aligned else None,
                label=entry_label(step=step, members=members),
                group=_(RISK_TEXT[step.risk]),
            ),
        )
        for index, step in enumerate(plan.steps)
    ]
    return tuple(entry for _risk, entry in sorted(ranked, key=lambda pair: pair[0]))


def entries_for(*, plan: Plan, snapshot: Snapshot | None) -> tuple[StepEntry, ...]:
    """One entry per step of ``plan``, labelled with the group each member belongs to."""
    names = _group_names(snapshot=snapshot)
    members = members_by_id(snapshot=snapshot)
    if plan.request.kind is ActionKind.DISK_FREE_SELECTED:
        return _selected_entries(plan=plan, members=members)
    entries = []
    for step in plan.steps:
        step_id = step_id_of(step=step)
        label = entry_label(step=step, members=members)
        entries.append(StepEntry(step_id=step_id, label=label, group=names.get(step_id or "")))
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
            (plan.request.kind in EXCLUDABLE_ACTIONS or self.kind is ActionKind.DISK_FREE_SELECTED)
            and (plan.request.kind is ActionKind.STOP_ALL_IDLE_SAFE or len(plan.steps) > 1)
            and all(entry.step_id is not None for entry in entries)
        )

    @property
    def has_exclusions(self) -> bool:
        """True once the user has unticked at least one entry."""
        return bool(self._excluded)

    def is_included(self, *, step_id: str) -> bool:
        """True while the entry is part of the request."""
        return step_id not in self._excluded

    def set_included(self, *, step_id: str, included: bool) -> None:
        """Include or exclude one entry and ask for the plan of what is left.

        With no entry left the plan is None and the dialog cannot be confirmed.
        """
        excluded = self._excluded - {step_id} if included else self._excluded | {step_id}
        self._excluded = excluded
        nothing_left = {entry.step_id for entry in self.entries} <= excluded
        if nothing_left and self.kind is ActionKind.DISK_FREE_SELECTED:
            self.plan, self.notice = None, None
            return
        request = self._request_without(excluded=excluded)
        try:
            plan = self._replan(request)
        except InvalidRequest as error:
            # Only "nothing left ticked" is the empty state; any other refusal says why.
            self.plan, self.notice = None, None if nothing_left else self._refusal(error=error)
            return
        except WimmError as error:
            LOGGER.warning("Plan refused after changing the entries: %s", error.message)
            self.plan, self.notice = None, _(error.user_message)
            return
        # The service plans on the latest snapshot: a target the list never showed must not
        # be confirmed through it.
        if self._shows_every_step(plan=plan, request=request):
            self.plan, self.notice = plan, None
        else:
            self.plan, self.notice = None, _(CHANGED_NOTICE)

    def _request_without(self, *, excluded: frozenset[str]) -> ActionRequest:
        """A selection drops the ticked rows it no longer wants; the others use excluded_ids."""
        if self.kind is ActionKind.DISK_FREE_SELECTED:
            return replace(self._request, selected_ids=self._request.selected_ids - excluded)
        return replace(self._request, excluded_ids=excluded)

    def _refusal(self, *, error: InvalidRequest) -> str:
        """S17: a row of the selection that is gone or changed is "the situation changed"."""
        if self.kind is ActionKind.DISK_FREE_SELECTED:
            return _(CHANGED_NOTICE)
        return _(error.user_message)

    def _shows_every_step(self, *, plan: Plan, request: ActionRequest) -> bool:
        if self.kind is ActionKind.DISK_FREE_SELECTED:
            return len(plan.steps) == len(request.selected_ids)
        shown = {entry.step_id for entry in self.entries}
        return all(step_id_of(step=step) in shown for step in plan.steps)
