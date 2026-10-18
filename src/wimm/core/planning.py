"""Pure construction of action plans (SPECIFICHE 8.1, 8.2). No I/O, no system reads."""

import secrets
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from wimm.model.actions import ActionRequest, Plan, PlanStep
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind, ActivityState, PlanId, Protection, Risk
from wimm.model.errors import InvalidRequest, ProtectedTarget
from wimm.model.snapshot import ContainerMember, Group, Member, ProcessMember, Snapshot

from .assemble_members import STOPPABLE_STATES
from .constants import PLAN_ID_BYTES, PLAN_TTL_S
from .planning_disk import DISK_PLANNERS, plan_cache_clean
from .planning_disk_safe import plan_disk_free_safe
from .planning_drafts import (
    APP_CLOSE_KINDS,
    Draft,
    app_close_draft,
    app_root,
    cmdline_hash,
    compose_draft,
    container_draft,
    is_actionable_process,
    process_draft,
)
from .planning_restart import StoppedContainer, plan_restart
from .planning_tools import ToolPlanner, no_tool

__all__ = ["PlanningContext", "cmdline_hash", "plan_action"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanningContext:
    """Sources the planner may not read itself.

    `owner_uid` is the user wimm runs as: processes of other users are never planned
    (spec 8.2 requires `uid == os.getuid()` at execution). The fingerprint carries the
    process's own uid, so the executor compares it against the live one. `disk_report` is
    the last disk scan, needed only by disk actions (images, volumes, caches, folders).
    `stopped` holds, by plan id, the containers recent plans stopped (C4, «Riaccendi»).
    `which` tells whether a tool is on PATH; the service passes the real lookup, and without
    it no command-only cache (Go modules) is offered.
    """

    owner_uid: int
    disk_report: DiskReport | None = None
    stopped: Mapping[str, tuple[StoppedContainer, ...]] = field(default_factory=dict)
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    new_plan_id: Callable[[], PlanId] = lambda: PlanId(secrets.token_urlsafe(PLAN_ID_BYTES))
    which: Callable[[str], str | None] = no_tool


class _Planner(Protocol):
    def __call__(
        self, *, request: ActionRequest, snapshot: Snapshot, owner_uid: int
    ) -> list[Draft]: ...


def _members(*, snapshot: Snapshot) -> Iterator[tuple[Group, Member]]:
    for group in snapshot.groups:
        for member in group.members:
            yield group, member


def _actionable_group(*, snapshot: Snapshot, group_id: str | None) -> Group:
    for group in snapshot.groups:
        if group.id == group_id:
            if group.protection is Protection.PROTECTED:
                raise ProtectedTarget(f"Group {group.id} is protected")
            return group
    raise InvalidRequest(f"Unknown group {group_id}")


def _plan_process(*, request: ActionRequest, snapshot: Snapshot, owner_uid: int) -> list[Draft]:
    for group, member in _members(snapshot=snapshot):
        if isinstance(member, ProcessMember) and str(member.pid) == request.target_id:
            if not is_actionable_process(group=group, member=member, owner_uid=owner_uid):
                raise ProtectedTarget(f"Process {member.pid} is protected or not actionable")
            return [process_draft(member=member, kind=request.kind)]
    raise InvalidRequest(f"Unknown process {request.target_id}")


def _plan_app_close(*, request: ActionRequest, snapshot: Snapshot, owner_uid: int) -> list[Draft]:
    """Plan one SIGTERM on the main process of an app group (spec 8.4), children untouched."""
    group = _actionable_group(snapshot=snapshot, group_id=request.group_id)
    if group.category not in APP_CLOSE_KINDS:
        raise InvalidRequest(f"Group {group.id} is not an app and cannot be closed")
    root = app_root(group=group)
    if not is_actionable_process(group=group, member=root, owner_uid=owner_uid):
        raise ProtectedTarget(f"Main process {root.pid} is protected or not actionable")
    return [app_close_draft(group=group, root=root)]


def _plan_container(*, request: ActionRequest, snapshot: Snapshot, owner_uid: int) -> list[Draft]:
    """Plan one container; the executor rechecks that it exists and its state fits (8.2)."""
    for _, member in _members(snapshot=snapshot):
        if isinstance(member, ContainerMember) and member.id == request.target_id:
            return [container_draft(member=member, kind=request.kind)]
    raise InvalidRequest(f"Unknown container {request.target_id}")


def _plan_compose(*, request: ActionRequest, snapshot: Snapshot, owner_uid: int) -> list[Draft]:
    group = _actionable_group(snapshot=snapshot, group_id=request.group_id)
    return [compose_draft(group=group, kind=request.kind)]


def _stop_drafts(*, group: Group, owner_uid: int) -> list[Draft]:
    drafts = [
        process_draft(member=member, kind=ActionKind.PROCESS_TERMINATE)
        for member in group.members
        if isinstance(member, ProcessMember)
        and is_actionable_process(group=group, member=member, owner_uid=owner_uid)
    ]
    drafts += [
        container_draft(member=member, kind=ActionKind.CONTAINER_STOP)
        for member in group.members
        if isinstance(member, ContainerMember) and member.state in STOPPABLE_STATES
    ]
    return drafts


def _kept(*, drafts: list[Draft], request: ActionRequest, group: Group) -> list[Draft]:
    if group.id in request.excluded_ids:
        return []
    return [draft for draft in drafts if not draft.owner_ids & request.excluded_ids]


def _plan_group_stop(*, request: ActionRequest, snapshot: Snapshot, owner_uid: int) -> list[Draft]:
    group = _actionable_group(snapshot=snapshot, group_id=request.group_id)
    drafts = _stop_drafts(group=group, owner_uid=owner_uid)
    return _kept(drafts=drafts, request=request, group=group)


def _plan_stop_all(*, request: ActionRequest, snapshot: Snapshot, owner_uid: int) -> list[Draft]:
    drafts: list[Draft] = []
    for group in snapshot.groups:
        candidates = _stop_drafts(group=group, owner_uid=owner_uid)
        idle = group.activity.state is ActivityState.IDLE and not group.ignored
        if idle and candidates and max(draft.risk for draft in candidates) is Risk.SAFE:
            drafts += _kept(drafts=candidates, request=request, group=group)
    return drafts


_PLANNERS: dict[ActionKind, _Planner] = {
    ActionKind.PROCESS_TERMINATE: _plan_process,
    ActionKind.PROCESS_KILL: _plan_process,
    ActionKind.APP_CLOSE: _plan_app_close,
    ActionKind.CONTAINER_STOP: _plan_container,
    ActionKind.CONTAINER_REMOVE: _plan_container,
    ActionKind.COMPOSE_DOWN: _plan_compose,
    ActionKind.COMPOSE_DOWN_VOLUMES: _plan_compose,
    ActionKind.GROUP_STOP: _plan_group_stop,
    ActionKind.STOP_ALL_IDLE_SAFE: _plan_stop_all,
}


_TOOL_PLANNERS: dict[ActionKind, ToolPlanner] = {
    ActionKind.CACHE_CLEAN: plan_cache_clean,
    ActionKind.DISK_FREE_SAFE: plan_disk_free_safe,
}


def _confirm_phrase(*, drafts: list[Draft]) -> str | None:
    danger = [draft for draft in drafts if draft.risk is Risk.DANGER]
    if not danger:
        return None
    if not danger[0].name.strip():
        raise InvalidRequest("A danger plan needs a non-empty target name to confirm")
    return danger[0].name


def _build_plan(*, request: ActionRequest, drafts: list[Draft], context: PlanningContext) -> Plan:
    if not drafts:
        raise InvalidRequest("Action has no executable steps")
    # Processes stop before containers, across groups too (spec 8.1, group_stop).
    drafts = sorted(drafts, key=lambda draft: draft.kind is ActionKind.CONTAINER_STOP)
    created_at = context.now()
    steps = tuple(
        PlanStep(
            order=order,
            kind=draft.kind,
            target_label=draft.label,
            fingerprint=draft.fingerprint,
            risk=draft.risk,
        )
        for order, draft in enumerate(drafts, start=1)
    )
    consequences = dict.fromkeys(line for d in drafts for line in d.assessed.consequences)
    return Plan(
        plan_id=context.new_plan_id(),
        request=request,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=PLAN_TTL_S),
        steps=steps,
        consequences=tuple(consequences),
        estimated_reclaim_ram=sum(draft.reclaim_ram for draft in drafts),
        estimated_reclaim_disk=sum(draft.reclaim_disk for draft in drafts),
        confirm_phrase=_confirm_phrase(drafts=drafts),
    )


def plan_action(*, request: ActionRequest, snapshot: Snapshot, context: PlanningContext) -> Plan:
    """Build the confirmation plan for a request, deterministic for equal inputs.

    Target ids are the pid, container id, volume name, image id, cache kind, folder path
    or group id; `excluded_ids` holds member or group ids. Disk actions read the report
    from `context.disk_report`; image and container prunes expand to one removal step per
    id (Q-13). With several danger steps `confirm_phrase` is the name
    of the first danger target in step order; with none it is None. A danger target
    with a blank name is refused rather than given an empty phrase.

    Raises
    ------
    ProtectedTarget
        If the target or its group is protected, offers no action, or the process
        belongs to another user.
    InvalidRequest
        If the target is unknown, the action does not apply to it, the kind is not
        plannable, no step is left, or a danger target has a blank name.
    """
    drafts = _drafts(request=request, snapshot=snapshot, context=context)
    return _build_plan(request=request, drafts=drafts, context=context)


def _drafts(*, request: ActionRequest, snapshot: Snapshot, context: PlanningContext) -> list[Draft]:
    """Pick the planner by what it reads: the stopped plans, the disk report or the snapshot."""
    if request.kind is ActionKind.RESTART_STOPPED:
        return plan_restart(request=request, stopped=context.stopped)
    tool_planner = _TOOL_PLANNERS.get(request.kind)
    if tool_planner is not None:
        return tool_planner(request=request, report=context.disk_report, which=context.which)
    disk_planner = DISK_PLANNERS.get(request.kind)
    if disk_planner is not None:
        return disk_planner(request=request, report=context.disk_report)
    planner = _PLANNERS.get(request.kind)
    if planner is None:
        raise InvalidRequest(f"Action {request.kind.value} cannot be planned")
    return planner(request=request, snapshot=snapshot, owner_uid=context.owner_uid)
