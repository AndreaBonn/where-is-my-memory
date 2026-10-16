"""Fakes and hand-built plans for executor tests. Nothing here touches the system."""

import signal
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from wimm.core.planning import cmdline_hash
from wimm.model.actions import (
    ActionRequest,
    ContainerFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind, GroupId, PlanId, Risk, TargetId
from wimm.service.control_protocols import LiveContainer, LiveProcess
from wimm.service.errors import ControlFailed

OWNER_UID = 1000
WIMM_PID = 900
CREATED_AT = 1_700_000_000.0
CMDLINE = ("python3", "-m", "http.server")


@dataclass(slots=True)
class FakeProcesses:
    live: dict[int, LiveProcess] = field(default_factory=dict)
    tree: dict[int, tuple[int, ...]] = field(default_factory=dict)
    lineage: frozenset[int] = frozenset({WIMM_PID, 1})
    stubborn: frozenset[int] = frozenset()
    failing: frozenset[int] = frozenset()
    crashing: frozenset[int] = frozenset()
    broken_trees: frozenset[int] = frozenset()
    on_wait: Callable[[], None] = lambda: None
    signals: list[tuple[int, signal.Signals]] = field(default_factory=list)
    waits: list[tuple[tuple[int, ...], float]] = field(default_factory=list)

    def inspect(self, *, pid: int) -> LiveProcess | None:
        return self.live.get(pid)

    def self_lineage(self) -> frozenset[int]:
        return self.lineage

    def descendants(self, *, pid: int) -> Sequence[int]:
        if pid in self.broken_trees:
            raise ControlFailed(f"cannot list children of {pid}")
        return self.tree.get(pid, ())

    def send_signal(self, *, pid: int, sig: signal.Signals) -> None:
        if pid in self.crashing:
            raise RuntimeError(f"unexpected failure signalling {pid}")
        if pid in self.failing:
            raise ControlFailed(f"cannot signal {pid}")
        self.signals.append((pid, sig))

    def wait_gone(self, *, pids: Sequence[int], timeout_s: float) -> frozenset[int]:
        self.waits.append((tuple(pids), timeout_s))
        self.on_wait()
        return frozenset(pid for pid in pids if pid in self.stubborn)


@dataclass(slots=True)
class FakeDocker:
    live: dict[str, LiveContainer] = field(default_factory=dict)
    failing: frozenset[str] = frozenset()
    crashing: frozenset[str] = frozenset()
    calls: list[tuple[str, str]] = field(default_factory=list)

    def inspect(self, *, container_id: str) -> LiveContainer | None:
        return self.live.get(container_id)

    def stop(self, *, container_id: str, timeout_s: int) -> None:
        if container_id in self.crashing:
            raise RuntimeError(f"unexpected failure stopping {container_id}")
        if container_id in self.failing:
            raise ControlFailed(f"cannot stop {container_id}")
        self.calls.append(("stop", f"{container_id}:{timeout_s}"))
        self.live[container_id] = LiveContainer(id=container_id, status="exited")

    def remove(self, *, container_id: str, volumes: bool) -> None:
        self.calls.append(("remove", f"{container_id}:v={volumes}"))
        self.live.pop(container_id, None)


def live_process(*, pid: int, uid: int = OWNER_UID, protected: bool = False) -> LiveProcess:
    return LiveProcess(
        pid=pid, create_time=CREATED_AT, uid=uid, cmdline=CMDLINE, protected=protected
    )


def process_step(
    *, order: int, pid: int, uid: int = OWNER_UID, kind: ActionKind = ActionKind.PROCESS_TERMINATE
) -> PlanStep:
    fingerprint = ProcessFingerprint(
        pid=pid, create_time=CREATED_AT, uid=uid, cmdline_hash=cmdline_hash(cmdline=CMDLINE)
    )
    return PlanStep(
        order=order,
        kind=kind,
        target_label=f"proc {pid}",
        fingerprint=fingerprint,
        risk=Risk.SAFE,
    )


def container_step(
    *, order: int, container_id: str, kind: ActionKind, status: str = "running"
) -> PlanStep:
    return PlanStep(
        order=order,
        kind=kind,
        target_label=container_id,
        fingerprint=ContainerFingerprint(id=container_id, status=status),
        risk=Risk.SAFE,
    )


def make_plan(*, steps: Sequence[PlanStep]) -> Plan:
    if len(steps) == 1 and steps[0].kind is ActionKind.APP_CLOSE:
        request = ActionRequest(kind=ActionKind.APP_CLOSE, group_id=GroupId("g_test"))
    elif len(steps) == 1:
        request = ActionRequest(kind=steps[0].kind, target_id=TargetId("target"))
    else:
        request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("g_test"))
    now = datetime.now(UTC)
    return Plan(
        plan_id=PlanId("plan-test"),
        request=request,
        created_at=now,
        expires_at=now + timedelta(seconds=120),
        steps=tuple(steps),
        consequences=(),
        estimated_reclaim_ram=0,
        estimated_reclaim_disk=0,
    )
