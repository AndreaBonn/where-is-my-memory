"""Typed seams between the executor and the system (psutil, Docker SDK)."""

import signal
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class StepStatus(Enum):
    DONE = "done"
    ALREADY_GONE = "already_gone"
    NOT_RESPONDING = "not_responding"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Result of one plan step; `message` is set for `failed` and `not_responding`."""

    order: int
    status: StepStatus
    message: str | None = None


@dataclass(frozen=True, slots=True)
class LiveProcess:
    """Current state of a process, read at execution time.

    `protected` is the live re-categorization verdict (SYSTEM, SESSION or SELF).
    """

    pid: int
    create_time: float
    uid: int
    cmdline: tuple[str, ...]
    protected: bool


@dataclass(frozen=True, slots=True)
class LiveContainer:
    id: str
    status: str


class ProcessControl(Protocol):
    def inspect(self, *, pid: int) -> LiveProcess | None:
        """Return the live process, or None if it no longer exists."""
        ...

    def self_lineage(self) -> frozenset[int]:
        """Return the pid of wimm and of all its ancestors."""
        ...

    def descendants(self, *, pid: int) -> Sequence[int]:
        """Return all descendants of `pid` (recursive), in discovery order."""
        ...

    def send_signal(self, *, pid: int, sig: signal.Signals) -> None:
        """Signal a process; a process that is already gone is not an error."""
        ...

    def wait_gone(self, *, pids: Sequence[int], timeout_s: float) -> frozenset[int]:
        """Wait up to `timeout_s`; return the pids still alive."""
        ...


class DockerControl(Protocol):
    def inspect(self, *, container_id: str) -> LiveContainer | None:
        """Return the live container, or None if it no longer exists."""
        ...

    def stop(self, *, container_id: str, timeout_s: int) -> None: ...

    def remove(self, *, container_id: str, volumes: bool) -> None: ...
