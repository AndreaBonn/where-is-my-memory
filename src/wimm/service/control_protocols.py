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
    """Result of one plan step; `message` is set for `failed` and `not_responding`.

    A `done` image removal may carry a note (tags left alone because they moved).

    `freed_bytes` is only set when the daemon reports it (the build cache prune).
    """

    order: int
    status: StepStatus
    message: str | None = None
    freed_bytes: int | None = None


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


@dataclass(frozen=True, slots=True)
class LiveImage:
    """`in_use`: some container, running or stopped, was created from exactly this image id.

    `has_children`: another image names this one as its parent, so the daemon refuses to
    delete the id (409) once its tags are gone.
    """

    id: str
    in_use: bool
    tags: tuple[str, ...] = ()
    has_children: bool = False


@dataclass(frozen=True, slots=True)
class LiveVolume:
    """`in_use`: some container, running or stopped, mounts the volume.

    `created_at` is Docker's `CreatedAt` string, kept verbatim: it tells a recreated volume
    from the one the plan showed. Empty when the daemon does not report it.
    """

    name: str
    in_use: bool
    created_at: str


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

    def inspect_image(self, *, image_id: str) -> LiveImage | None:
        """Return the live image, or None if it no longer exists."""
        ...

    def resolve_image(self, *, ref: str) -> str | None:
        """Return the id `ref` (a tag) points to right now, or None if it no longer exists."""
        ...

    def remove_image(self, *, ref: str) -> None:
        """Remove a reference: a tag untags (the last tag deletes the image), an id deletes it.

        Raise `TargetGone` if the reference does not exist (anymore).
        """
        ...

    def inspect_volume(self, *, name: str) -> LiveVolume | None:
        """Return the live volume, or None if it no longer exists."""
        ...

    def remove_volume(self, *, name: str) -> None:
        """Remove the volume; raise `TargetGone` if it does not exist (anymore)."""
        ...

    def prune_build_cache(self) -> int:
        """Remove every unused build cache record; return the `SpaceReclaimed` of the daemon."""
        ...


class ComposeControl(Protocol):
    def container_ids(self, *, project: str) -> frozenset[str]:
        """Return the ids of every container, running or not, labelled with the project."""
        ...

    def down(self, *, project: str, volumes: bool) -> None:
        """Run `compose down` (with `-v` if `volumes`); raise `ControlFailed` on any failure."""
        ...
