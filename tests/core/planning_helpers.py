from datetime import UTC, datetime

from wimm.core.planning import PlanningContext
from wimm.core.risk import RiskTarget, available_actions
from wimm.model.enums import ActivityState, Category, GroupId, PlanId, Pressure
from wimm.model.memory import DiskUsage, MemoryBreakdown, MemorySummary, MemoryUse, Reclaimable
from wimm.model.raw import Mount
from wimm.model.snapshot import (
    ActivityAssessment,
    ContainerMember,
    DockerStatus,
    Group,
    Member,
    ProcessMember,
    Snapshot,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
OWNER_UID = 1000


def context() -> PlanningContext:
    return PlanningContext(owner_uid=OWNER_UID, now=lambda: NOW, new_plan_id=lambda: PlanId("p-1"))


def activity(state: ActivityState) -> ActivityAssessment:
    since = None if state is ActivityState.UNKNOWN else NOW
    return ActivityAssessment(state=state, since=since, reason="test")


def proc(
    *,
    pid: int,
    name: str = "node",
    category: Category = Category.DEV_SERVER,
    state: ActivityState = ActivityState.IDLE,
    reclaimable: int = 100,
    uid: int = OWNER_UID,
    has_documents: bool = False,
    is_foreground: bool = False,
) -> ProcessMember:
    target = RiskTarget(
        kind="process",
        category=category,
        activity=state,
        process_name=name,
        cwd="/work/app",
        has_documents=has_documents,
        is_foreground_on_tty=is_foreground,
    )
    return ProcessMember(
        pid=pid,
        create_time=1000.5 + pid,
        uid=uid,
        name=name,
        cmdline=("node", "server.js"),
        cwd="/work/app",
        category=category,
        listen_ports=(),
        memory=MemoryUse(used=reclaimable * 2, reclaimable=reclaimable),
        activity=activity(state),
        actions=available_actions(target=target),
        has_documents=has_documents,
        is_foreground=is_foreground,
    )


def container(
    *,
    cid: str,
    state: str = "running",
    reclaimable: int = 300,
    mounts: tuple[Mount, ...] = (),
) -> ContainerMember:
    target = RiskTarget(
        kind="container", category=Category.CONTAINER, is_running=state == "running"
    )
    return ContainerMember(
        id=cid,
        name=f"name-{cid}",
        image="img",
        state=state,
        memory=MemoryUse(used=reclaimable, reclaimable=reclaimable),
        mounts=mounts,
        activity=activity(ActivityState.IDLE),
        actions=available_actions(target=target),
    )


def group(
    *,
    gid: str,
    members: tuple[Member, ...],
    category: Category = Category.PROJECT,
    state: ActivityState = ActivityState.IDLE,
    ignored: bool = False,
    name: str | None = None,
    compose_project: str | None = None,
) -> Group:
    return Group(
        id=GroupId(gid),
        name=name or f"name-{gid}",
        category=category,
        activity=activity(state),
        memory=MemoryUse(used=0, reclaimable=0),
        ports=(),
        primary_action=None,
        ignored=ignored,
        snoozed_until=None,
        explanation="",
        compose_project=compose_project,
        members=members,
    )


def snapshot(*groups: Group) -> Snapshot:
    summary = MemorySummary(
        total=10,
        available=5,
        used=5,
        swap_total=0,
        swap_used=0,
        breakdown=MemoryBreakdown(categories=(), kernel_cache=0, unattributed=0),
    )
    return Snapshot(
        taken_at=NOW,
        monitor_started_at=NOW,
        memory=summary,
        disk=DiskUsage(mount="/", total=10, used=5, free=5),
        reclaimable_now=Reclaimable(ram=0, disk=0),
        pressure=Pressure.OK,
        docker=DockerStatus(available=True, error=None),
        groups=groups,
        protected_summary=(),
    )
