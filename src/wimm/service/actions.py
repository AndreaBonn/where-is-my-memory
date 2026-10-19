"""Seams and value types of the action flow in `AppService` (SPECIFICHE 8.1)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from wimm.config import Config
from wimm.model.actions import EngineIdentity, Plan
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
        ActionKind.CACHE_ITEM_REMOVE,
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
    the freed memory and disk are measured (spec 8.1, step 6). `engine_identities` reads the
    engines the executor's controls act on, from the same pool, for the plan to record (S9).
    """

    executor: ActionExecutor
    owner_uid: int
    measure_delay_s: float = RECLAIM_MEASURE_DELAY_S
    engine_identities: Callable[[], tuple[EngineIdentity, ...]] = lambda: ()


@dataclass(frozen=True, slots=True)
class ReclaimDelta:
    """Change of `MemAvailable` and of free disk space across an action, in bytes.

    Negative when the system used more than the action released.
    """

    freed_ram: int
    freed_disk: int


# Requests whose plans never hold a container step: reading the engines for them would only
# risk waiting on an unresponsive socket while planning a kill.
ENGINE_FREE_KINDS = frozenset(
    {
        ActionKind.PROCESS_TERMINATE,
        ActionKind.PROCESS_KILL,
        ActionKind.APP_CLOSE,
        ActionKind.CACHE_CLEAN,
        ActionKind.CACHE_ITEM_REMOVE,
        ActionKind.TRASH_EMPTY,
        ActionKind.DEVDIR_DELETE,
    }
)


def plan_engines(*, setup: ActionSetup, kind: ActionKind) -> tuple[EngineIdentity, ...]:
    """The engine identities a plan of ``kind`` must record for the S9 check."""
    return () if kind in ENGINE_FREE_KINDS else setup.engine_identities()
