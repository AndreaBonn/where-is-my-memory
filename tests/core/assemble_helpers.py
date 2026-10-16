from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TypedDict, Unpack

from wimm.core.assemble import (
    AssemblyInput,
    Entities,
    SystemState,
    Thresholds,
    UserState,
    Verdicts,
)
from wimm.core.categorize import CategoryDecision
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.model.enums import ActivityState, Category, GroupId, MetricsSource
from wimm.model.memory import DiskUsage
from wimm.model.raw import Mount, RawContainer, RawProcess
from wimm.model.snapshot import ActivityAssessment, DockerStatus

from .helpers import meminfo, process

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
STARTED = NOW - timedelta(hours=4)
IDLE = ActivityAssessment(state=ActivityState.IDLE, since=NOW - timedelta(hours=1), reason="idle")
ACTIVE = ActivityAssessment(
    state=ActivityState.ACTIVE, since=NOW - timedelta(minutes=2), reason="active"
)
UNKNOWN = ActivityAssessment(state=ActivityState.UNKNOWN, since=None, reason="unknown")
ROOT_DISK = DiskUsage(mount="/", total=1000, used=500, free=500)
DOCKER_UP = DockerStatus(available=True, error=None)
SESSION_KEY = "session-gnome"
SYSTEM_KEY = "system-services"

START_TIME = 1760590000.0
Pair = tuple[RawProcess, CategoryDecision]


class ProcessChanges(TypedDict, total=False):
    create_time: float | None
    name: str
    cwd: str | None
    pss: int | None
    uss: int | None
    swap: int | None
    rss: int
    uid: int
    cgroup: str
    tpgid: int | None
    pgid: int | None


def pair(
    pid: int, category: Category | None = Category.DEV_PROCESS, **changes: Unpack[ProcessChanges]
) -> Pair:
    proc = replace(process(pid=pid), create_time=START_TIME)
    proc = replace(proc, **changes)
    return proc, CategoryDecision(category=category, reason_code="x")


def container(
    name: str, *, memory: int = 100, state: str = "running", ports: tuple[int, ...] = ()
) -> RawContainer:
    return RawContainer(
        id=f"id-{name}",
        name=name,
        image="img",
        state=state,
        labels=(),
        mounts=(Mount(type="volume", source="v", destination="/v"),),
        ports=ports,
        pid=900,
        memory_bytes=memory,
        cpu_usage_usec=0,
        net_bytes=None,
        metrics_source=MetricsSource.CGROUP,
    )


def draft(
    gid: str,
    *,
    name: str = "group",
    category: Category = Category.DEV_PROCESS,
    pids: Sequence[int] = (),
    containers: Sequence[str] = (),
    key: str = "k",
) -> GroupDraft:
    return GroupDraft(
        id=GroupId(gid),
        key=key,
        name=name,
        category=category,
        process_pids=tuple(pids),
        container_ids=tuple(f"id-{item}" for item in containers),
        compose_project=None,
        working_dir=None,
        explanation=f"explanation of {name}",
    )


def build_input(
    drafts: Sequence[GroupDraft],
    *,
    pairs: Sequence[Pair] = (),
    containers: Sequence[RawContainer] = (),
    ports: Mapping[int, frozenset[int]] | None = None,
    verdicts: Mapping[int, ActivityAssessment] | None = None,
    container_verdicts: Mapping[str, ActivityAssessment] | None = None,
    system: SystemState | None = None,
    user: UserState | None = None,
    thresholds: Thresholds | None = None,
) -> AssemblyInput:
    return AssemblyInput(
        drafts=tuple(drafts),
        entities=Entities(
            processes={item[0].pid: item for item in pairs},
            containers={item.id: item for item in containers},
            listen_ports_by_pid=ports or {},
            desktop_categories={},
        ),
        verdicts=Verdicts(
            by_pid=verdicts if verdicts is not None else {item[0].pid: IDLE for item in pairs},
            by_container=container_verdicts
            if container_verdicts is not None
            else {item.id: IDLE for item in containers},
        ),
        system=system or SystemState(mem=meminfo(), disks=(ROOT_DISK,), docker=DOCKER_UP),
        taken_at=NOW,
        monitor_started_at=STARTED,
        user=user or UserState(),
        thresholds=thresholds or Thresholds(),
    )


HOME = "/home/bonn"
WHITEBOX_DIR = "/home/bonn/dev/ai-whitebox-core"
COMPOSE_PROJECT = "com.docker.compose.project"
COMPOSE_WORKDIR = "com.docker.compose.project.working_dir"
UVICORN_PID = 30


def whitebox_input() -> AssemblyInput:
    """Compose project with two containers fused with an idle uvicorn on port 8000."""
    labels = ((COMPOSE_PROJECT, "whitebox"), (COMPOSE_WORKDIR, WHITEBOX_DIR))
    keycloak = replace(container("keycloak", memory=680, ports=(8080,)), labels=labels)
    postgres = replace(container("postgres", memory=300), labels=labels)
    uvicorn = pair(
        UVICORN_PID,
        Category.DEV_SERVER,
        name="uvicorn",
        cwd=WHITEBOX_DIR + "/app",
        pss=180,
        uss=165,
        swap=0,
    )
    drafts = build_groups(
        grouping=GroupingInput(
            pairs=(uvicorn,),
            containers=(keycloak, postgres),
            project_root_by_cwd={WHITEBOX_DIR + "/app": WHITEBOX_DIR},
            desktop_name_by_appid={},
            own_home=HOME,
            own_uid=1000,
            listen_ports_by_pid={UVICORN_PID: frozenset({8000})},
        )
    )
    return build_input(
        drafts,
        pairs=(uvicorn,),
        containers=(keycloak, postgres),
        ports={UVICORN_PID: frozenset({8000})},
    )
