from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from wimm.model.enums import ActionKind, Category, Pressure, Risk


@dataclass(frozen=True, slots=True)
class RowFilters:
    only_idle: bool = False
    categories: frozenset[Category] = frozenset()
    risks: frozenset[Risk] = frozenset()
    query: str = ""


class EmptyKind(Enum):
    NOTHING_IDLE = "nothing_idle"
    NO_RESULTS = "no_results"


@dataclass(frozen=True, slots=True)
class EmptyStateView:
    kind: EmptyKind
    message: str


@dataclass(frozen=True, slots=True)
class BarSegment:
    key: str
    label: str
    size: int
    size_text: str
    percent: int
    fraction: float
    legend: str


@dataclass(frozen=True, slots=True)
class SummaryView:
    ram_used: str
    ram_total: str
    ram_available: str
    ram_fraction: float
    swap_used: str
    swap_total: str
    disk_mount: str
    disk_used: str
    disk_total: str
    disk_free: str
    disk_fraction: float
    ram_headline: str
    ram_details: str
    disk_headline: str
    reclaimable_ram: str
    reclaimable_disk: str
    pressure: Pressure
    pressure_text: str
    segments: tuple[BarSegment, ...]
    kernel_cache_note: str


@dataclass(frozen=True, slots=True)
class ActionButton:
    label: str
    kind: ActionKind
    risk: Risk


@dataclass(frozen=True, slots=True)
class MemberRow:
    key: str
    kind: str
    name: str
    command: str | None
    cwd: str | None
    ports: str
    started: str | None
    memory: str
    image: str | None
    state: str | None
    mounts: tuple[str, ...]
    activity: str
    actions: tuple[ActionButton, ...]


@dataclass(frozen=True, slots=True)
class GroupRow:
    id: str
    title: str
    subtitle: str
    detail: str
    reclaimable: str
    memory: str
    risk: Risk | None
    risk_text: str
    risk_style: str
    primary_action: ActionButton | None
    explanation: str
    members: tuple[MemberRow, ...]
    ignored: bool
    snoozed_until: datetime | None
    snoozed_text: str | None


@dataclass(frozen=True, slots=True)
class SystemRow:
    label: str
    memory: str
    reason: str
