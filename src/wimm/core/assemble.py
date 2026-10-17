"""Snapshot assembly (SPECIFICHE 6.4 point 4, 6.5): pure, no I/O, no clock.

The sampler collects, categorizes, groups and assesses activity; this module only
combines those results into the `Snapshot` it publishes.

Protected groups (SYSTEM, SESSION, SELF) appear only in `protected_summary`, but their
memory still counts in the breakdown. Groups are ordered by reclaimable memory,
descending (RF-03). "Reclaimable now" skips ignored groups; a snoozed group still
counts, because snoozing only silences notifications for a while (RF-27).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from itertools import chain

from wimm.i18n import N_, _
from wimm.model.enums import (
    ActionKind,
    ActivityState,
    Category,
    GroupId,
    Pressure,
    Protection,
    protection_of,
)
from wimm.model.memory import DiskUsage
from wimm.model.raw import MemInfo, RawContainer, RawProcess
from wimm.model.snapshot import (
    ActionOffer,
    ActivityAssessment,
    ContainerMember,
    DockerStatus,
    Group,
    Member,
    ProtectedSummaryItem,
    Snapshot,
)

from . import text
from .activity import GroupMember, assess_group_activity, is_measurable
from .assemble_members import ProcessFacts, build_container_member, build_process_member
from .categorize import CategoryDecision
from .constants import PRESSURE_CRITICAL_PCT, PRESSURE_WARNING_PCT
from .grouping import GroupDraft
from .grouping_keys import LABEL_AUDIO, LABEL_OTHER_USERS, LABEL_SELF, LABEL_SESSION, LABEL_SYSTEM
from .memory import group_memory, memory_summary, pressure, reclaimable_now
from .risk import RiskTarget, TargetKind, available_actions, group_primary_action

PRESSURE_ORDER = (Pressure.OK, Pressure.WARNING, Pressure.CRITICAL)
APP_TARGET_KINDS: Mapping[Category, TargetKind] = {
    Category.BROWSER: "browser",
    Category.DESKTOP_APP: "desktop_app",
    Category.TERMINAL: "terminal",
}
PROTECTED_REASONS: Mapping[str, str] = {
    LABEL_AUDIO[0]: N_("audio e media del desktop"),
    LABEL_SESSION[0]: N_("componente del desktop"),
    LABEL_OTHER_USERS[0]: N_("processi di altri utenti, non modificabili da qui"),
    LABEL_SYSTEM[0]: N_("servizio di sistema"),
    LABEL_SELF[0]: N_("questa applicazione"),
}


@dataclass(frozen=True, slots=True)
class Entities:
    """Collected and categorized facts, keyed by pid and container id."""

    processes: Mapping[int, tuple[RawProcess, CategoryDecision]]
    containers: Mapping[str, RawContainer]
    listen_ports_by_pid: Mapping[int, frozenset[int]]
    desktop_categories: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class Verdicts:
    """Activity assessments computed by the sampler from its history.

    A process without a verdict (protected ones are never sampled) is not evaluated.
    A container always needs one.
    """

    by_pid: Mapping[int, ActivityAssessment]
    by_container: Mapping[str, ActivityAssessment]


@dataclass(frozen=True, slots=True)
class SystemState:
    """System-wide counters; `disks` lists the root disk first (SPECIFICHE 7.5)."""

    mem: MemInfo
    disks: tuple[DiskUsage, ...]
    docker: DockerStatus
    reclaimable_disk: int = 0


@dataclass(frozen=True, slots=True)
class UserState:
    """Per-group choices of the user (RF-27)."""

    ignored: frozenset[GroupId] = frozenset()
    snoozed_until: Mapping[GroupId, datetime] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Pressure thresholds in percent of available RAM or free disk."""

    warning_pct: float = PRESSURE_WARNING_PCT
    critical_pct: float = PRESSURE_CRITICAL_PCT


@dataclass(frozen=True, slots=True)
class AssemblyInput:
    """Everything `assemble_snapshot` needs, already collected and assessed."""

    drafts: tuple[GroupDraft, ...]
    entities: Entities
    verdicts: Verdicts
    system: SystemState
    taken_at: datetime
    monitor_started_at: datetime
    user: UserState = field(default_factory=UserState)
    thresholds: Thresholds = field(default_factory=Thresholds)

    def __post_init__(self) -> None:
        if not self.system.disks:
            raise ValueError("at least one disk is required")
        pids = [pid for item in self.drafts for pid in item.process_pids]
        containers = [cid for item in self.drafts for cid in item.container_ids]
        if len(pids) != len(set(pids)) or len(containers) != len(set(containers)):
            raise ValueError("a process or container is in more than one group")


def _members(*, draft: GroupDraft, inputs: AssemblyInput) -> tuple[Member, ...]:
    entities, verdicts = inputs.entities, inputs.verdicts
    not_evaluated = ActivityAssessment(
        state=ActivityState.UNKNOWN, since=None, reason=text.reason_not_evaluated()
    )
    processes = tuple(
        build_process_member(
            facts=ProcessFacts(
                proc=entities.processes[pid][0],
                decision=entities.processes[pid][1],
                listen_ports=entities.listen_ports_by_pid.get(pid, frozenset()),
                activity=verdicts.by_pid.get(pid, not_evaluated),
            ),
            desktop_categories=entities.desktop_categories,
        )
        for pid in draft.process_pids
    )
    containers = tuple(
        build_container_member(
            container=entities.containers[container_id],
            activity=verdicts.by_container[container_id],
        )
        for container_id in draft.container_ids
    )
    return processes + containers


def _is_measurable(*, member: Member) -> bool:
    category = Category.CONTAINER if isinstance(member, ContainerMember) else member.category
    return is_measurable(category=category)


def _primary_action(*, category: Category, members: tuple[Member, ...]) -> ActionOffer | None:
    """Apps close as a whole (`app_close`); other groups aggregate their members' offers.

    A removal offer of a dead container does not weigh on the group: its risk comes from
    the stop actions of the members that can be stopped.
    """
    offers = tuple(member.actions[0] for member in members if member.actions)
    if offers and category in APP_TARGET_KINDS:
        offers = available_actions(
            target=RiskTarget(kind=APP_TARGET_KINDS[category], category=category)
        )
    primary = group_primary_action(member_offers=offers, group_kind=category)
    stops = [offer for offer in offers if offer.kind is not ActionKind.CONTAINER_REMOVE]
    if primary is None or not stops:
        return primary
    return ActionOffer(kind=primary.kind, risk=max(offer.risk for offer in stops))


def _ports(*, draft: GroupDraft, inputs: AssemblyInput) -> tuple[int, ...]:
    entities = inputs.entities
    process_ports = (
        entities.listen_ports_by_pid.get(pid, frozenset()) for pid in draft.process_pids
    )
    container_ports = (entities.containers[item].ports for item in draft.container_ids)
    return tuple(sorted(set(chain.from_iterable(chain(process_ports, container_ports)))))


def _snoozed_until(*, group_id: GroupId, inputs: AssemblyInput) -> datetime | None:
    until = inputs.user.snoozed_until.get(group_id)
    return until if until is not None and until > inputs.taken_at else None


def _build_group(*, draft: GroupDraft, inputs: AssemblyInput) -> Group:
    members = _members(draft=draft, inputs=inputs)
    activity = assess_group_activity(
        members=[
            GroupMember(assessment=member.activity, measurable=_is_measurable(member=member))
            for member in members
        ]
    )
    return Group(
        id=draft.id,
        name=draft.name,
        category=draft.category,
        activity=activity,
        memory=group_memory(members=members),
        ports=_ports(draft=draft, inputs=inputs),
        primary_action=_primary_action(category=draft.category, members=members),
        ignored=draft.id in inputs.user.ignored,
        snoozed_until=_snoozed_until(group_id=draft.id, inputs=inputs),
        explanation=draft.explanation,
        compose_project=draft.compose_project,
        members=members,
    )


def _worst_pressure(*, inputs: AssemblyInput) -> Pressure:
    levels = (
        pressure(
            mem=inputs.system.mem,
            disk=disk,
            warning_pct=inputs.thresholds.warning_pct,
            critical_pct=inputs.thresholds.critical_pct,
        )
        for disk in inputs.system.disks
    )
    return max(levels, key=PRESSURE_ORDER.index)


def _protected_item(*, draft: GroupDraft, group: Group) -> ProtectedSummaryItem:
    return ProtectedSummaryItem(
        label=draft.name, memory=group.memory.used, reason=_(PROTECTED_REASONS[draft.key])
    )


def _ranked(*, groups: list[Group]) -> tuple[Group, ...]:
    return tuple(sorted(groups, key=lambda item: (-item.memory.reclaimable, item.name, item.id)))


def _actionable(*, built: list[tuple[GroupDraft, Group]]) -> list[Group]:
    return [
        group
        for draft, group in built
        if protection_of(category=draft.category) is Protection.ACTIONABLE
    ]


def _protected_summary(
    *, built: list[tuple[GroupDraft, Group]]
) -> tuple[ProtectedSummaryItem, ...]:
    items = [
        _protected_item(draft=draft, group=group)
        for draft, group in built
        if protection_of(category=draft.category) is Protection.PROTECTED
    ]
    return tuple(sorted(items, key=lambda item: (-item.memory, item.label)))


def assemble_snapshot(*, inputs: AssemblyInput) -> Snapshot:
    """Combine collected, grouped and assessed data into a Snapshot (SPECIFICHE 6.5).

    Parameters
    ----------
    inputs : AssemblyInput
        Drafts from `build_groups`, entities, verdicts, system counters and user state.

    Raises
    ------
    ValueError
        If the memory or disk totals are zero (from `pressure`).
    """
    built = [(draft, _build_group(draft=draft, inputs=inputs)) for draft in inputs.drafts]
    actionable = _actionable(built=built)
    return Snapshot(
        taken_at=inputs.taken_at,
        monitor_started_at=inputs.monitor_started_at,
        memory=memory_summary(mem=inputs.system.mem, groups=[group for _key, group in built]),
        disk=inputs.system.disks[0],
        reclaimable_now=reclaimable_now(
            groups=actionable, disk_bytes=inputs.system.reclaimable_disk
        ),
        pressure=_worst_pressure(inputs=inputs),
        docker=inputs.system.docker,
        groups=_ranked(groups=actionable),
        protected_summary=_protected_summary(built=built),
    )
