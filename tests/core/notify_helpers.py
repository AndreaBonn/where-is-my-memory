from dataclasses import replace
from datetime import UTC, datetime, timedelta

from wimm.config import Config
from wimm.core.notify_rules import NotificationState, NotifyRequest
from wimm.model.enums import ActivityState, Category, GroupId, Pressure
from wimm.model.memory import DiskUsage, MemoryBreakdown, MemorySummary, MemoryUse, Reclaimable
from wimm.model.snapshot import (
    ActivityAssessment,
    DockerStatus,
    Group,
    Member,
    Snapshot,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
GB = 1_000_000_000
MB = 1_000_000
TOTAL_RAM = 100 * GB
TOTAL_DISK = 1000 * GB


def idle_since(*, hours: float = 3.0) -> ActivityAssessment:
    return ActivityAssessment(
        state=ActivityState.IDLE, since=NOW - timedelta(hours=hours), reason="idle"
    )


def make_group(
    gid: str = "g_1",
    *,
    name: str = "whitebox",
    category: Category = Category.CONTAINER,
    activity: ActivityAssessment | None = None,
    reclaimable: int = GB,
    ignored: bool = False,
    snoozed_until: datetime | None = None,
    members: tuple[Member, ...] = (),
) -> Group:
    return Group(
        id=GroupId(gid),
        name=name,
        category=category,
        activity=activity or idle_since(),
        memory=MemoryUse(used=reclaimable * 2, reclaimable=reclaimable),
        ports=(),
        primary_action=None,
        ignored=ignored,
        snoozed_until=snoozed_until,
        explanation="",
        compose_project=None,
        members=members,
    )


def make_snapshot(
    groups: tuple[Group, ...] = (),
    *,
    ram_free_pct: int = 50,
    disk_free_pct: int = 50,
    reclaimable_disk: int = 0,
) -> Snapshot:
    available = TOTAL_RAM * ram_free_pct // 100
    free = TOTAL_DISK * disk_free_pct // 100
    breakdown = MemoryBreakdown(categories=(), kernel_cache=0, unattributed=0)
    memory = MemorySummary(
        total=TOTAL_RAM,
        available=available,
        used=TOTAL_RAM - available,
        swap_total=0,
        swap_used=0,
        breakdown=breakdown,
    )
    return Snapshot(
        taken_at=NOW,
        monitor_started_at=NOW - timedelta(days=1),
        memory=memory,
        disk=DiskUsage(mount="/", total=TOTAL_DISK, used=TOTAL_DISK - free, free=free),
        reclaimable_now=Reclaimable(
            ram=sum(g.memory.reclaimable for g in groups), disk=reclaimable_disk
        ),
        pressure=Pressure.OK,
        docker=DockerStatus(available=True, error=None),
        groups=groups,
        protected_summary=(),
    )


def request(
    snapshot: Snapshot,
    *,
    state: NotificationState | None = None,
    now: datetime = NOW,
    muted_until: datetime | None = None,
    config: Config | None = None,
) -> NotifyRequest:
    return NotifyRequest(
        snapshot=snapshot,
        config=config or Config(),
        state=state or NotificationState(),
        now=now,
        muted_until=muted_until,
    )


def with_config(
    *,
    notify_categories: frozenset[Category] | None = None,
    notify_after_s: int | None = None,
    pressure_critical_pct: int | None = None,
    pressure_warning_pct: int | None = None,
) -> Config:
    base = Config()
    return replace(
        base,
        notify_categories=notify_categories or base.notify_categories,
        notify_after_s=notify_after_s or base.notify_after_s,
        pressure_critical_pct=pressure_critical_pct or base.pressure_critical_pct,
        pressure_warning_pct=pressure_warning_pct or base.pressure_warning_pct,
    )
