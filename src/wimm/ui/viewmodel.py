import shlex
from datetime import datetime

from wimm.model.enums import ActivityState, Protection, Risk
from wimm.model.snapshot import (
    ActionOffer,
    ContainerMember,
    Group,
    Member,
    ProcessMember,
    Snapshot,
)

from .format import (
    CATEGORY_LABELS,
    RISK_CONSEQUENCE,
    RISK_STYLE,
    activity_text,
    button_label,
    fold_text,
    format_clock,
    format_size,
)
from .plain import friendly_container_name, friendly_process_name, plain_reason, titled_name
from .summary import build_summary as build_summary
from .views import (
    ActionButton,
    EmptyKind,
    EmptyStateView,
    GroupRow,
    MemberRow,
    RowFilters,
    SystemRow,
)

NEUTRAL_STYLE = "dim-label"
NO_ACTION_BADGE = "Nessuna azione"
NOTHING_IDLE_MESSAGE = "Niente da liberare: il resto è in uso o ancora in osservazione."
NO_RESULTS_MESSAGE = "Nessun programma corrisponde ai filtri."
ALL_CLEAR_MESSAGE = "Tutto in ordine"
ALL_CLEAR_DESCRIPTION = (
    "Non c'è niente acceso che si possa chiudere. "
    "Ti avvisiamo noi se qualcosa resta acceso senza motivo."
)
PORTS_SEPARATOR = ", "
DETAIL_SEPARATOR = " · "


def ports_text(*, ports: tuple[int, ...]) -> str:
    return PORTS_SEPARATOR.join(str(port) for port in ports)


def action_button(*, offer: ActionOffer) -> ActionButton:
    return ActionButton(label=button_label(kind=offer.kind), kind=offer.kind, risk=offer.risk)


def _elapsed(*, since: datetime | None, now: datetime) -> float | None:
    return None if since is None else max((now - since).total_seconds(), 0.0)


def _activity(*, member_or_group: Group | Member, now: datetime) -> str:
    activity = member_or_group.activity
    return activity_text(
        state=activity.state,
        reason=activity.reason,
        elapsed_s=_elapsed(since=activity.since, now=now),
    )


def _mount_text(*, member: ContainerMember) -> tuple[str, ...]:
    return tuple(f"{m.type}: {m.source} -> {m.destination}" for m in member.mounts)


def _process_row(*, member: ProcessMember, now: datetime) -> MemberRow:
    started = datetime.fromtimestamp(member.create_time, tz=now.tzinfo)
    return MemberRow(
        key=str(member.pid),
        kind="process",
        name=member.name,
        title=titled_name(name=member.name, friendly=friendly_process_name(name=member.name)),
        command=shlex.join(member.cmdline) if member.cmdline else None,
        cwd=member.cwd,
        ports=ports_text(ports=member.listen_ports),
        started=format_clock(value=started, now=now),
        memory=format_size(size=member.memory.used),
        image=None,
        state=None,
        mounts=(),
        activity=_activity(member_or_group=member, now=now),
        actions=tuple(action_button(offer=offer) for offer in member.actions),
    )


def _container_row(*, member: ContainerMember, now: datetime) -> MemberRow:
    return MemberRow(
        key=member.id,
        kind="container",
        name=member.name,
        title=titled_name(name=member.name, friendly=friendly_container_name(image=member.image)),
        command=None,
        cwd=None,
        ports="",
        started=None,
        memory=format_size(size=member.memory.used),
        image=member.image,
        state=member.state,
        mounts=_mount_text(member=member),
        activity=_activity(member_or_group=member, now=now),
        actions=tuple(action_button(offer=offer) for offer in member.actions),
    )


def _member_row(*, member: Member, now: datetime) -> MemberRow:
    if isinstance(member, ProcessMember):
        return _process_row(member=member, now=now)
    return _container_row(member=member, now=now)


def _row_risk(*, group: Group) -> Risk | None:
    if group.primary_action is not None:
        return group.primary_action.risk
    if not group.actions:
        return None
    return max(offer.risk for offer in group.actions)


def _badge(*, risk: Risk | None) -> tuple[str, str]:
    if risk is None:
        return NO_ACTION_BADGE, NEUTRAL_STYLE
    return RISK_CONSEQUENCE[risk], RISK_STYLE[risk]


def _detail(*, group: Group) -> str:
    parts = [group.activity.reason]
    if group.ports:
        noun = "porta" if len(group.ports) == 1 else "porte"
        parts.append(f"{noun} {ports_text(ports=group.ports)}")
    return DETAIL_SEPARATOR.join(parts)


def _snooze(*, group: Group, now: datetime) -> tuple[datetime | None, str | None]:
    until = group.snoozed_until
    if until is None or until <= now:
        return None, None
    local = until.astimezone(now.tzinfo)
    if local.date() == now.date():
        text = f"avvisi in pausa fino alle {local:%H:%M}"
    else:
        text = f"avvisi in pausa fino al {local:%d/%m} alle {local:%H:%M}"
    return until, text


def _group_row(*, group: Group, now: datetime) -> GroupRow:
    risk = _row_risk(group=group)
    badge_text, badge_style = _badge(risk=risk)
    until, until_text = _snooze(group=group, now=now)
    primary = group.primary_action
    return GroupRow(
        id=group.id,
        title=group.name,
        subtitle=f"{CATEGORY_LABELS[group.category]} · {_activity(member_or_group=group, now=now)}",
        detail=plain_reason(activity=group.activity, now=now),
        technical=_detail(group=group),
        is_idle=group.activity.state is ActivityState.IDLE,
        reclaimable=format_size(size=group.memory.reclaimable),
        memory=format_size(size=group.memory.used),
        risk=risk,
        risk_text=badge_text,
        risk_style=badge_style,
        primary_action=None if primary is None else action_button(offer=primary),
        explanation=group.explanation,
        members=tuple(_member_row(member=member, now=now) for member in group.members),
        ignored=group.ignored,
        snoozed_until=until,
        snoozed_text=until_text,
    )


def _member_text(*, member: Member) -> list[str]:
    if isinstance(member, ProcessMember):
        return [member.name, " ".join(member.cmdline), ports_text(ports=member.listen_ports)]
    return [member.name, member.image]


def _searchable(*, group: Group) -> str:
    parts = [group.name, group.explanation, ports_text(ports=group.ports)]
    for member in group.members:
        parts += _member_text(member=member)
    return fold_text(text="\n".join(parts))


def _matches(*, group: Group, filters: RowFilters) -> bool:
    if filters.only_idle and group.activity.state is not ActivityState.IDLE:
        return False
    if filters.categories and group.category not in filters.categories:
        return False
    if filters.risks and _row_risk(group=group) not in filters.risks:
        return False
    query = fold_text(text=filters.query.strip())
    return not query or query in _searchable(group=group)


def _select_groups(*, snapshot: Snapshot, filters: RowFilters) -> list[Group]:
    # Protected entities live only in the System view (spec 10.2, RF-07).
    chosen = [
        group
        for group in snapshot.groups
        if group.protection is Protection.ACTIONABLE and _matches(group=group, filters=filters)
    ]
    # P9: what the user can free comes first. Ties fall back to used memory, name and id
    # so the order never flickers.
    chosen.sort(
        key=lambda g: (
            g.activity.state is not ActivityState.IDLE,
            -g.memory.reclaimable,
            -g.memory.used,
            g.name.casefold(),
            g.id,
        ),
    )
    return chosen


def build_rows(*, snapshot: Snapshot, filters: RowFilters, now: datetime) -> tuple[GroupRow, ...]:
    """Filter and order the groups, unused ones first (P9), then build their rows.

    Parameters
    ----------
    snapshot : Snapshot
        Latest observation.
    filters : RowFilters
        Idle-only flag, category and risk sets, case-insensitive search text.
    now : datetime
        Time anchor for durations and local clock times.

    Returns
    -------
    tuple[GroupRow, ...]
        Idle rows first, then the others; each part by reclaimable memory, largest first.
    """
    groups = _select_groups(snapshot=snapshot, filters=filters)
    return tuple(_group_row(group=group, now=now) for group in groups)


def filter_counts(*, snapshot: Snapshot) -> tuple[int, int]:
    """How many programs "Da liberare" and "Tutto" list, before the other filters (P5)."""
    everything = _select_groups(snapshot=snapshot, filters=RowFilters())
    idle = sum(group.activity.state is ActivityState.IDLE for group in everything)
    return idle, len(everything)


def build_system_rows(*, snapshot: Snapshot) -> tuple[SystemRow, ...]:
    """Build the read-only System view from the protected summary (RF-07), largest first."""
    ranked = sorted(snapshot.protected_summary, key=lambda item: (-item.memory, item.label))
    return tuple(
        SystemRow(label=item.label, memory=format_size(size=item.memory), reason=item.reason)
        for item in ranked
    )


def empty_state(*, snapshot: Snapshot, filters: RowFilters) -> EmptyStateView | None:
    """Return the empty-state message when no group is shown, else None (spec 10.3)."""
    if _select_groups(snapshot=snapshot, filters=filters):
        return None
    if filters.categories or filters.risks or filters.query.strip():
        return EmptyStateView(kind=EmptyKind.NO_RESULTS, message=NO_RESULTS_MESSAGE)
    if not _select_groups(snapshot=snapshot, filters=RowFilters()):
        return EmptyStateView(
            kind=EmptyKind.ALL_CLEAR, message=ALL_CLEAR_MESSAGE, description=ALL_CLEAR_DESCRIPTION
        )
    if filters.only_idle:
        return EmptyStateView(kind=EmptyKind.NOTHING_IDLE, message=NOTHING_IDLE_MESSAGE)
    return None
