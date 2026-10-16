"""Single-target step drafts for the planner (SPECIFICHE 8.1, 8.2). Pure, no I/O."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from wimm.model.actions import (
    ComposeFingerprint,
    ContainerFingerprint,
    Fingerprint,
    ProcessFingerprint,
    VolumeFingerprint,
)
from wimm.model.enums import ActionKind, Category, Protection, Risk
from wimm.model.errors import InvalidRequest
from wimm.model.snapshot import ContainerMember, Group, ProcessMember

from .assemble_members import STOPPABLE_STATES
from .risk import RiskAssessment, RiskTarget, TargetKind, assess_risk

# `app_close` targets desktop apps, browsers and terminals (sections 5.3 and 8.4).
APP_CLOSE_KINDS: Mapping[Category, TargetKind] = {
    Category.BROWSER: "browser",
    Category.DESKTOP_APP: "desktop_app",
    # Section 5.3: closing a terminal ends gnome-terminal-server, the group's root, not a shell.
    Category.TERMINAL: "terminal",
}
ARGV_SEPARATOR = "\0"
VOLUME_MOUNT_TYPE = "volume"


@dataclass(frozen=True, slots=True)
class Draft:
    """One planned step. `owner_ids` are the ids that exclude it; `name` confirms danger."""

    owner_ids: frozenset[str]
    kind: ActionKind
    label: str
    name: str
    fingerprint: Fingerprint
    assessed: RiskAssessment
    reclaim_ram: int

    @property
    def risk(self) -> Risk:
        return self.assessed.level


def cmdline_hash(*, cmdline: tuple[str, ...]) -> str:
    """Return the stable SHA-256 of an argv, as stored in a process fingerprint."""
    joined = ARGV_SEPARATOR.join(cmdline)
    return hashlib.sha256(joined.encode(encoding="utf-8", errors="replace")).hexdigest()


def _assess(*, target: RiskTarget, kind: ActionKind) -> RiskAssessment:
    try:
        return assess_risk(target=target, action=kind)
    except ValueError as error:
        raise InvalidRequest(str(error)) from error


def is_actionable_process(*, group: Group, member: ProcessMember, owner_uid: int) -> bool:
    """True if the process may be planned: not protected, offered actions, owned by the user."""
    return (
        group.protection is Protection.ACTIONABLE
        and member.protection is Protection.ACTIONABLE
        and bool(member.actions)
        and member.uid == owner_uid
    )


def _fingerprint(*, member: ProcessMember) -> ProcessFingerprint:
    return ProcessFingerprint(
        pid=member.pid,
        create_time=member.create_time,
        uid=member.uid,
        cmdline_hash=cmdline_hash(cmdline=member.cmdline),
    )


def process_draft(*, member: ProcessMember, kind: ActionKind) -> Draft:
    """Draft a process step, risk assessed from the member's full risk facts."""
    target = RiskTarget(
        kind="process",
        category=member.category,
        activity=member.activity.state,
        is_foreground_on_tty=member.is_foreground,
        has_documents=member.has_documents,
        process_name=member.name,
        cwd=member.cwd,
    )
    fingerprint = ProcessFingerprint(
        pid=member.pid,
        create_time=member.create_time,
        uid=member.uid,
        cmdline_hash=cmdline_hash(cmdline=member.cmdline),
    )
    return Draft(
        owner_ids=frozenset({str(member.pid)}),
        kind=kind,
        label=f"{member.name} (pid {member.pid})",
        name=member.name,
        fingerprint=fingerprint,
        assessed=_assess(target=target, kind=kind),
        reclaim_ram=member.memory.reclaimable,
    )


def container_draft(*, member: ContainerMember, kind: ActionKind) -> Draft:
    """Draft a container step; the state is part of the fingerprint."""
    running = member.state in STOPPABLE_STATES
    target = RiskTarget(kind="container", category=Category.CONTAINER, is_running=running)
    return Draft(
        owner_ids=frozenset({member.id}),
        kind=kind,
        label=member.name,
        name=member.name,
        fingerprint=ContainerFingerprint(id=member.id, status=member.state),
        assessed=_assess(target=target, kind=kind),
        reclaim_ram=member.memory.reclaimable,
    )


def compose_draft(*, group: Group, kind: ActionKind) -> Draft:
    """Draft a compose project step covering the group's containers and their volumes."""
    containers = [m for m in group.members if isinstance(m, ContainerMember)]
    if not containers:
        raise InvalidRequest(f"Group {group.id} has no containers")
    volumes = {
        PurePosixPath(mount.source).parent.name
        for member in containers
        for mount in member.mounts
        if mount.type == VOLUME_MOUNT_TYPE
    }
    target = RiskTarget(
        kind="compose_project", category=group.category, volume_names=tuple(sorted(volumes))
    )
    ids = frozenset(m.id for m in containers)
    return Draft(
        owner_ids=frozenset({group.id}),
        kind=kind,
        label=group.name,
        name=group.name,
        fingerprint=ComposeFingerprint(project=group.name, container_ids=ids),
        assessed=_assess(target=target, kind=kind),
        reclaim_ram=sum(m.memory.reclaimable for m in containers),
    )


def volume_draft(*, name: str, kind: ActionKind) -> Draft:
    """Draft a volume removal; the reclaim is unknown to the snapshot, hence zero."""
    return Draft(
        owner_ids=frozenset({name}),
        kind=kind,
        label=name,
        name=name,
        fingerprint=VolumeFingerprint(name=name),
        assessed=_assess(target=RiskTarget(kind="volume"), kind=kind),
        reclaim_ram=0,
    )


def app_root(*, group: Group) -> ProcessMember:
    """Return the main process of an app group: the root of its process tree.

    The snapshot carries no parent pid, and a child never starts before its parent, so the
    oldest member (lowest `create_time`) cannot have a parent inside the group: it is a
    root. Among equally old members the lowest pid wins, because a parent's pid is almost
    always lower than its children's (pids grow, wrapping aside).

    Limit: a helper that started before the app, and is grouped with it, is older and so
    is chosen, and it receives the signal instead of the app.
    """
    members = [member for member in group.members if isinstance(member, ProcessMember)]
    if not members:
        raise InvalidRequest(f"Group {group.id} has no processes")
    return min(members, key=lambda m: (m.create_time, m.pid))


def app_close_draft(*, group: Group, root: ProcessMember) -> Draft:
    """Draft the single `app_close` step on the group's main process.

    Risk is assessed on the whole app (documents of any member, the app kind of the
    group); the label and the danger phrase use the app name, not the process name.
    """
    processes = [m for m in group.members if isinstance(m, ProcessMember)]
    target = RiskTarget(
        kind=APP_CLOSE_KINDS[group.category],
        category=group.category,
        activity=root.activity.state,
        is_foreground_on_tty=root.is_foreground,
        has_documents=any(member.has_documents for member in processes),
        process_name=root.name,
        cwd=root.cwd,
    )
    return Draft(
        owner_ids=frozenset({group.id}),
        kind=ActionKind.APP_CLOSE,
        label=f"{group.name} (pid {root.pid})",
        name=group.name,
        fingerprint=_fingerprint(member=root),
        assessed=_assess(target=target, kind=ActionKind.APP_CLOSE),
        reclaim_ram=sum(member.memory.reclaimable for member in processes),
    )
