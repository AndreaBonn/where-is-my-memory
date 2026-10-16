"""Targets created by integration tests themselves, and plans built on them by hand."""

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import psutil

from wimm.core.planning import cmdline_hash
from wimm.model.actions import (
    ActionRequest,
    ContainerFingerprint,
    Plan,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId

READY_LINE = "ready"
STUBBORN_SCRIPT = (
    "import signal, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    f"print({READY_LINE!r}, flush=True)\n"
    "time.sleep(60)\n"
)
PARENT_SCRIPT = (
    "import subprocess, time\n"
    "subprocess.Popen(['sleep', '60'])\n"
    f"print({READY_LINE!r}, flush=True)\n"
    "time.sleep(60)\n"
)


@contextmanager
def spawned(*, args: list[str]) -> Iterator[subprocess.Popen[str]]:
    """Start a process owned by the test and always kill and reap it afterwards."""
    child = subprocess.Popen(
        args=args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    try:
        yield child
    finally:
        child.kill()
        child.wait(timeout=10)


def python_child(*, script: str) -> list[str]:
    return [sys.executable, "-c", script]


def wait_ready(*, child: subprocess.Popen[str]) -> None:
    assert child.stdout is not None
    assert child.stdout.readline().strip() == READY_LINE


def process_step(*, pid: int, order: int = 1) -> PlanStep:
    process = psutil.Process(pid)
    fingerprint = ProcessFingerprint(
        pid=pid,
        create_time=process.create_time(),
        uid=int(process.uids().real),
        cmdline_hash=cmdline_hash(cmdline=tuple(process.cmdline())),
    )
    return PlanStep(
        order=order,
        kind=ActionKind.PROCESS_TERMINATE,
        target_label=f"pid {pid}",
        fingerprint=fingerprint,
        risk=Risk.SAFE,
    )


def container_step(
    *, container_id: str, kind: ActionKind, order: int = 1, status: str = "running"
) -> PlanStep:
    return PlanStep(
        order=order,
        kind=kind,
        target_label=container_id[:12],
        fingerprint=ContainerFingerprint(id=container_id, status=status),
        risk=Risk.SAFE,
    )


def single_step_plan(*, step: PlanStep) -> Plan:
    now = datetime.now(UTC)
    return Plan(
        plan_id=PlanId("integration-plan"),
        request=ActionRequest(kind=step.kind, target_id=TargetId("target")),
        created_at=now,
        expires_at=now + timedelta(seconds=120),
        steps=(step,),
        consequences=(),
        estimated_reclaim_ram=0,
        estimated_reclaim_disk=0,
    )
