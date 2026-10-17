from dataclasses import replace
from datetime import UTC, datetime
from typing import TypedDict, Unpack

from wimm.model.enums import ActivityState, Category, GroupId
from wimm.model.memory import MemoryUse
from wimm.model.raw import MemInfo, RawProcess
from wimm.model.snapshot import ActionOffer, ActivityAssessment, Group, Member, ProcessMember

USER_PATH = "/user.slice/user-1000.slice/user@1000.service/app.slice/"
VTE = USER_PATH + "app-org.gnome.Terminal.slice/vte-spawn-uuid.scope"
TERMINAL = USER_PATH + "app-org.gnome.Terminal.slice/gnome-terminal-server.service"
FIREFOX = USER_PATH + "snap.firefox.firefox-uuid.scope"
DOCKER = "/system.slice/docker-" + "a1b2c3d4" * 8 + ".scope"
OLLAMA = "/system.slice/ollama.service"


class ProcessChanges(TypedDict, total=False):
    pid: int
    ppid: int
    uid: int
    name: str
    exe: str | None
    cmdline: tuple[str, ...] | None
    cwd: str | None
    create_time: float | None
    cpu_time_s: float | None
    pss: int | None
    uss: int | None
    swap: int | None
    rss: int
    cgroup: str
    terminal: str | None
    tpgid: int | None
    pgid: int | None


class GroupChanges(TypedDict, total=False):
    category: Category
    primary_action: ActionOffer | None
    members: tuple[Member, ...]


def process(**changes: Unpack[ProcessChanges]) -> RawProcess:
    base = RawProcess(
        pid=20,
        ppid=1,
        uid=1000,
        name="worker",
        exe=None,
        cmdline=None,
        cwd=None,
        create_time=None,
        cpu_time_s=None,
        pss=100,
        uss=60,
        swap=10,
        rss=150,
        cgroup=VTE,
        terminal=None,
        tpgid=None,
        pgid=None,
    )
    return replace(base, **changes)


def meminfo(**changes: int) -> MemInfo:
    base = MemInfo(
        mem_total=1000,
        mem_free=100,
        mem_available=300,
        cached=100,
        buffers=20,
        s_reclaimable=30,
        shmem=10,
        swap_total=200,
        swap_free=150,
    )
    return replace(base, **changes)


def group(**changes: Unpack[GroupChanges]) -> Group:
    activity = ActivityAssessment(
        state=ActivityState.IDLE, since=datetime(2026, 1, 1, tzinfo=UTC), reason="idle"
    )
    base = Group(
        id=GroupId("g1"),
        name="group",
        category=Category.DEV_SERVER,
        activity=activity,
        memory=MemoryUse(used=100, reclaimable=70),
        ports=(),
        primary_action=None,
        ignored=False,
        snoozed_until=None,
        explanation="",
        compose_project=None,
        members=(),
    )
    return replace(base, **changes)


def member(category: Category) -> ProcessMember:
    return ProcessMember(
        pid=20,
        create_time=1,
        uid=1000,
        name="worker",
        cmdline=(),
        cwd=None,
        category=category,
        listen_ports=(),
        memory=MemoryUse(used=100, reclaimable=70),
        activity=group().activity,
        actions=(),
        has_documents=False,
        is_foreground=False,
    )
