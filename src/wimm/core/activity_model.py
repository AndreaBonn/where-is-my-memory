from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from wimm.model.enums import Category
from wimm.model.snapshot import ActivityAssessment
from wimm.model.validation import ImmutableModel

type Quadruple = tuple[str, int, str, int]


class EntityKind(Enum):
    SERVER = "server"
    PROCESS = "process"
    CONTAINER = "container"
    FOREGROUND = "foreground"
    NOT_EVALUATED = "not_evaluated"


# OTHER and PROJECT are not in the 5.4 table; they are not evaluated rather than guessed.
KIND_BY_CATEGORY: Mapping[Category, EntityKind] = MappingProxyType(
    {
        Category.DEV_SERVER: EntityKind.SERVER,
        Category.DEV_PROCESS: EntityKind.PROCESS,
        Category.AI_CLI: EntityKind.PROCESS,
        Category.CONTAINER: EntityKind.CONTAINER,
        Category.BROWSER: EntityKind.FOREGROUND,
        Category.DESKTOP_APP: EntityKind.FOREGROUND,
        Category.TERMINAL: EntityKind.FOREGROUND,
        Category.SYSTEM: EntityKind.NOT_EVALUATED,
        Category.SESSION: EntityKind.NOT_EVALUATED,
        Category.SELF: EntityKind.NOT_EVALUATED,
        Category.OTHER: EntityKind.NOT_EVALUATED,
        Category.PROJECT: EntityKind.NOT_EVALUATED,
    }
)
# Kinds whose activity comes from CPU, connections or network deltas.
MEASURABLE_KINDS = frozenset({EntityKind.SERVER, EntityKind.PROCESS, EntityKind.CONTAINER})
# Categories judged by being in the foreground; the sampler tracks them via the X11 window.
FOREGROUND_CATEGORIES = frozenset(
    category for category, kind in KIND_BY_CATEGORY.items() if kind is EntityKind.FOREGROUND
)


def kind_of(*, category: Category) -> EntityKind:
    return KIND_BY_CATEGORY[category]


def is_measurable(*, category: Category) -> bool:
    kind = kind_of(category=category)
    return kind in MEASURABLE_KINDS or kind is EntityKind.FOREGROUND


@dataclass(frozen=True, slots=True)
class EntitySample(ImmutableModel):
    """One observation of an entity.

    ``cpu_time_s`` is cumulative CPU seconds (process plus children, or the container's
    ``cpu_usage_usec`` converted); ``connections`` holds the non-LISTEN quadruples on the
    server's ports (None: not measured this cycle); ``foreground`` tells whether the
    entity's app group was in the foreground this cycle (None: not measurable, as on
    Wayland or with tracking off).
    """

    taken_at: datetime
    cpu_time_s: float | None
    connections: frozenset[Quadruple] | None = frozenset()
    net_bytes: int | None = None
    foreground: bool | None = None


@dataclass(frozen=True, slots=True)
class ActivityConfig:
    window_s: int
    interval_s: int
    cpu_threshold_pct: float
    net_threshold_bps: float


@dataclass(frozen=True, slots=True)
class ActivityInputs(ImmutableModel):
    """Everything ``assess_activity`` needs about one entity.

    ``history`` is oldest first. ``persisted_last_active`` must only be set when the
    persisted identity matches this entity (pid + create_time, or container id).
    ``server_ports`` are the LISTEN ports, used to name the port in the HMR reason.
    """

    category: Category
    history: tuple[EntitySample, ...]
    now: datetime
    # None when the creation time is unknown (a container): it then bounds nothing.
    created_at: datetime | None
    monitor_started_at: datetime
    persisted_last_active: datetime | None = None
    server_ports: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class GroupMember:
    assessment: ActivityAssessment
    measurable: bool
