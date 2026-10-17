"""Seams and value types of the action flow in `AppService` (SPECIFICHE 8.1)."""

from dataclasses import dataclass
from typing import Protocol

from wimm.config import Config
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind

from .control_protocols import StepOutcome

RECLAIM_MEASURE_DELAY_S = 3.0
# Requests that change what the disk report shows: the service rescans after they run.
DISK_REQUEST_KINDS = frozenset(
    {
        ActionKind.IMAGE_REMOVE,
        ActionKind.IMAGES_PRUNE_DANGLING,
        ActionKind.IMAGES_PRUNE_UNUSED,
        ActionKind.CONTAINERS_PRUNE_STOPPED,
        ActionKind.BUILDER_PRUNE,
        ActionKind.VOLUME_REMOVE,
        ActionKind.CACHE_CLEAN,
        ActionKind.TRASH_EMPTY,
        ActionKind.DEVDIR_DELETE,
        ActionKind.DISK_FREE_SAFE,
    }
)


class ActionExecutor(Protocol):
    def apply_config(self, *, config: Config) -> None:
        """Adopt a new configuration; called on the worker, between two plans."""
        ...

    def execute(self, *, plan: Plan) -> tuple[StepOutcome, ...]:
        """Run a confirmed plan; raise a `WimmError` to reject it as a whole."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionSetup:
    """What the service needs to plan and run actions.

    `owner_uid` is the user wimm runs as. `measure_delay_s` is how long after an action
    the freed memory and disk are measured (spec 8.1, step 6).
    """

    executor: ActionExecutor
    owner_uid: int
    measure_delay_s: float = RECLAIM_MEASURE_DELAY_S


@dataclass(frozen=True, slots=True)
class ReclaimDelta:
    """Change of `MemAvailable` and of free disk space across an action, in bytes.

    Negative when the system used more than the action released.
    """

    freed_ram: int
    freed_disk: int
