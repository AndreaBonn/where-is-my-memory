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
    ALL_CLEAR = "all_clear"


@dataclass(frozen=True, slots=True)
class EmptyStateView:
    kind: EmptyKind
    message: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class BarSegment:
    key: str
    label: str
    size: int
    size_text: str
    percent: int
    fraction: float
    legend: str
    help_question: str = ""
    help_answer: str = ""


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
    pressure: Pressure
    pressure_text: str
    segments: tuple[BarSegment, ...]
    kernel_cache_note: str
    status_title: str
    status_text: str
    status_level: str
    safe_label: str
    safe_text: str
    reclaim_headline: str
    reclaim_details: str
    disk_safe_label: str
    review_text: str
    video_title: str = ""
    video_lines: tuple[str, ...] = ()


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
    title: str
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
    technical: str
    is_idle: bool
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
    growth_text: str | None = None


@dataclass(frozen=True, slots=True)
class SystemRow:
    label: str
    memory: str
    reason: str
