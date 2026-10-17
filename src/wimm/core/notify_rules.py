from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType

from wimm.config import Config
from wimm.core import constants as c
from wimm.core.sizes import format_size
from wimm.core.text import spoken_duration
from wimm.model.enums import ActivityState, Category, GroupId, Protection
from wimm.model.snapshot import ContainerMember, Group, ProcessMember, Snapshot

PERCENT = 100
AGGREGATE_ID = "idle-aggregate"
PRESSURE_KINDS = ("ram", "disk")
Episode = tuple[GroupId, datetime]


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    """A notification to show; ``group_id`` feeds the open/snooze actions (None if no group)."""

    id: str
    title: str
    body: str
    group_id: GroupId | None


@dataclass(frozen=True, slots=True)
class NotificationState:
    """What was already notified: idle episodes, last pressure per kind, send times."""

    episodes: frozenset[Episode] = frozenset()
    pressure_sent: Mapping[str, datetime] = field(default_factory=lambda: MappingProxyType({}))
    sent_at: tuple[datetime, ...] = ()


@dataclass(frozen=True, slots=True)
class NotifyRequest:
    """Everything the rules need, clock included; ``muted_until`` is the global silence."""

    snapshot: Snapshot
    config: Config
    state: NotificationState
    now: datetime
    muted_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class NotifyResult:
    intents: tuple[NotificationIntent, ...]
    state: NotificationState


def _is_silenced(*, group: Group, now: datetime) -> bool:
    return group.snoozed_until is not None and group.snoozed_until > now


def _idle_since(*, group: Group) -> datetime | None:
    return group.activity.since if group.activity.state is ActivityState.IDLE else None


def _is_idle_candidate(*, group: Group, request: NotifyRequest) -> bool:
    since = _idle_since(group=group)
    config = request.config
    return (
        since is not None
        and group.protection is Protection.ACTIONABLE
        and request.now - since >= timedelta(seconds=config.notify_after_s)
        and group.memory.reclaimable >= config.notify_min_bytes
        and not group.ignored
        and not _is_silenced(group=group, now=request.now)
        and group.category in config.notify_categories
        and (group.id, since) not in request.state.episodes
    )


def _idle_candidates(*, request: NotifyRequest) -> list[Group]:
    found = [g for g in request.snapshot.groups if _is_idle_candidate(group=g, request=request)]
    return sorted(found, key=lambda g: (-g.memory.reclaimable, g.id))


def _join(*, parts: list[str]) -> str:
    if len(parts) < 2:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} e {parts[-1]}"


def _member_summary(*, group: Group) -> str:
    containers = sum(isinstance(m, ContainerMember) for m in group.members)
    procs = [m for m in group.members if isinstance(m, ProcessMember)]
    servers = sum(m.category is Category.DEV_SERVER for m in procs)
    others = len(procs) - servers
    parts = [
        f"{containers} container" if containers else "",
        f"{servers} server" if servers else "",
        f"{others} {'processo' if others == 1 else 'processi'}" if others else "",
    ]
    return _join(parts=[p for p in parts if p])


def _idle_intent(*, group: Group, now: datetime) -> NotificationIntent:
    since = group.activity.since
    elapsed = spoken_duration(seconds=(now - since).total_seconds()) if since else ""
    body = (
        f"Chiudendolo liberi {format_size(size=group.memory.reclaimable)} di memoria. "
        "Decidi tu: non si chiude da solo."
    )
    members = _member_summary(group=group)
    return NotificationIntent(
        id=f"idle-{group.id}",
        title=f"{group.name} è acceso ma non lo usi da {elapsed}",
        body=f"{body} Dentro: {members}." if members else body,
        group_id=group.id,
    )


def _aggregate_intent(*, groups: list[Group]) -> NotificationIntent:
    count = len(groups)
    size = format_size(size=sum(g.memory.reclaimable for g in groups))
    if count == 1:
        title, verb, pronoun = "1 programma acceso che non usi", "Chiudendolo", "vederlo"
    else:
        title, verb, pronoun = f"{count} programmi accesi che non usi", "Chiudendoli", "vederli"
    return NotificationIntent(
        id=AGGREGATE_ID,
        title=title,
        body=f"{verb} liberi {size} di memoria. Apri il pannello per {pronoun}.",
        group_id=None,
    )


def _free_pct(*, free: int, total: int) -> int | None:
    return None if total <= 0 else free * PERCENT // total


def _ram_intent(*, snapshot: Snapshot, pct: int) -> NotificationIntent:
    usable = [
        g
        for g in snapshot.groups
        if g.protection is Protection.ACTIONABLE and not g.ignored and g.memory.reclaimable > 0
    ]
    top = sorted(usable, key=lambda g: (-g.memory.reclaimable, g.id))[: c.PRESSURE_TOP_GROUPS]
    listed = ", ".join(f"{g.name} {format_size(size=g.memory.reclaimable)}" for g in top)
    return NotificationIntent(
        id="pressure-ram",
        title=f"Memoria quasi piena ({pct}% libera)",
        body=f"Puoi liberare subito: {listed}."
        if top
        else "Apri il pannello per vedere cosa chiudere.",
        group_id=None,
    )


def _disk_intent(*, snapshot: Snapshot, pct: int) -> NotificationIntent:
    size = snapshot.reclaimable_now.disk
    body = (
        f"Puoi liberare subito {format_size(size=size)} sul disco."
        if size > 0
        else "Apri il pannello per vedere cosa occupa spazio."
    )
    return NotificationIntent(
        id="pressure-disk", title=f"Disco quasi pieno ({pct}% libero)", body=body, group_id=None
    )


def _pressure_due(*, request: NotifyRequest, kind: str, pct: int | None) -> bool:
    if pct is None or pct >= request.config.pressure_critical_pct:
        return False
    last = request.state.pressure_sent.get(kind)
    # A send "in the future" means the clock moved back: do not stay silent until then.
    if last is None or last > request.now:
        return True
    return request.now - last >= timedelta(seconds=c.PRESSURE_COOLDOWN_S)


def _pressure_intents(*, request: NotifyRequest) -> list[tuple[str, NotificationIntent]]:
    snap = request.snapshot
    ram = _free_pct(free=snap.memory.available, total=snap.memory.total)
    disk = _free_pct(free=snap.disk.free, total=snap.disk.total)
    found: list[tuple[str, NotificationIntent]] = []
    if ram is not None and _pressure_due(request=request, kind="ram", pct=ram):
        found.append(("ram", _ram_intent(snapshot=snap, pct=ram)))
    if disk is not None and _pressure_due(request=request, kind="disk", pct=disk):
        found.append(("disk", _disk_intent(snapshot=snap, pct=disk)))
    return found


def _live_episodes(*, request: NotifyRequest) -> frozenset[Episode]:
    """Keep only episodes still present in the snapshot, so the state cannot grow forever."""
    live = {(g.id, s) for g in request.snapshot.groups if (s := _idle_since(group=g)) is not None}
    return frozenset(request.state.episodes & live)


def _recent_sends(*, request: NotifyRequest) -> tuple[datetime, ...]:
    window = timedelta(seconds=c.NOTIFY_WINDOW_S)
    # Sends "in the future" (clock moved back) are dropped rather than blocking the window.
    return tuple(t for t in request.state.sent_at if timedelta(0) <= request.now - t < window)


def _split_idle(*, candidates: list[Group], slots: int) -> tuple[list[Group], list[Group]]:
    if slots <= 0:
        return [], []
    return candidates[:slots], candidates[slots:]


def evaluate_notifications(*, request: NotifyRequest) -> NotifyResult:
    """Decide which notifications to show now (SPECIFICHE § 9). Pure: no I/O, no clock.

    Pressure notifications go first and are never aggregated: a critical state must
    not be hidden, and its own 1 h cooldown per kind keeps it at most twice an hour.
    Idle notifications use the slots left in the 60 minute window
    (``max_notifications_per_hour``); the overflow becomes one aggregate and is
    recorded as notified. With no slots left, idle episodes are deferred, not lost.
    During the global silence nothing is sent and nothing is recorded, so episodes
    and pressure still true when it ends are notified then.
    """
    recent = _recent_sends(request=request)
    episodes = _live_episodes(request=request)
    if request.muted_until is not None and request.now < request.muted_until:
        state = NotificationState(episodes, request.state.pressure_sent, recent)
        return NotifyResult(intents=(), state=state)
    pressure = _pressure_intents(request=request)
    slots = request.config.max_notifications_per_hour - len(recent) - len(pressure)
    shown, overflow = _split_idle(candidates=_idle_candidates(request=request), slots=slots)
    intents = [i for _, i in pressure] + [_idle_intent(group=g, now=request.now) for g in shown]
    if overflow:
        intents.append(_aggregate_intent(groups=overflow))
    marked = {(g.id, g.activity.since) for g in (*shown, *overflow) if g.activity.since}
    sent = {**request.state.pressure_sent, **{kind: request.now for kind, _ in pressure}}
    state = NotificationState(
        episodes | frozenset(marked),
        MappingProxyType(sent),
        (*recent, *[request.now] * len(intents)),
    )
    return NotifyResult(intents=tuple(intents), state=state)
