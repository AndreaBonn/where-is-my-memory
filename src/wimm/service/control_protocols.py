"""Typed seams between the executor and the system (psutil, Docker SDK)."""

import logging
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .errors import WimmError


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


LOGGER = logging.getLogger(__name__)
UNEXPECTED_FAILURE = "unexpected error, see the log"


def failed_outcome(*, order: int, error: Exception) -> StepOutcome:
    """Turn any error raised by one step into its `failed` outcome.

    A `WimmError` carries its own message; anything else is logged with its traceback and
    reported generically, so the steps after it still run and earlier ones are not lost.
    """
    if isinstance(error, WimmError):
        message = error.message
    else:
        LOGGER.error("Step %d failed unexpectedly", order, exc_info=error)
        message = UNEXPECTED_FAILURE
    return StepOutcome(order=order, status=StepStatus.FAILED, message=message)


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

    def set_extra_protected_names(self, *, names: tuple[str, ...]) -> None:
        """Replace the user's extra protected process names, effective at the next inspect."""
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


class ComposeControl(Protocol):
    def container_ids(self, *, project: str) -> frozenset[str]:
        """Return the ids of every container, running or not, labelled with the project."""
        ...

    def down(self, *, project: str, volumes: bool) -> None:
        """Run `compose down` (with `-v` if `volumes`); raise `ControlFailed` on any failure."""
        ...
