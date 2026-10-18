from dataclasses import dataclass
from datetime import datetime

from .enums import (
    ActionKind,
    ActivityState,
    Category,
    GroupId,
    Pressure,
    Protection,
    Risk,
    protection_of,
)
from .memory import DiskUsage, MemorySummary, MemoryUse, Reclaimable
from .raw import Mount
from .validation import (
    ImmutableModel,
    require_aware,
    require_bytes,
    require_nonnegative,
    require_ports,
)


@dataclass(frozen=True, slots=True)
class ActivityAssessment(ImmutableModel):
    state: ActivityState
    since: datetime | None
    reason: str

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        if self.since is not None:
            require_aware(value=self.since, field="since")
        elif self.state is not ActivityState.UNKNOWN:
            raise ValueError("since is required for active and idle activity")


@dataclass(frozen=True, slots=True)
class ActionOffer(ImmutableModel):
    kind: ActionKind
    risk: Risk


def require_protected_actions(category: Category, actions: tuple[ActionOffer, ...]) -> None:
    if protection_of(category=category) is Protection.PROTECTED and actions:
        raise ValueError("protected category must not offer actions or primary_action")


@dataclass(frozen=True, slots=True)
class ProcessMember(ImmutableModel):
    pid: int
    create_time: float
    uid: int
    name: str
    cmdline: tuple[str, ...]
    cwd: str | None
    category: Category
    listen_ports: tuple[int, ...]
    memory: MemoryUse
    activity: ActivityAssessment
    actions: tuple[ActionOffer, ...]
    has_documents: bool
    is_foreground: bool
    # Keys of the recognised developer tool (``ToolLabel``/``ToolReason`` values), or None.
    tool_label: str | None = None
    tool_reason: str | None = None

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_nonnegative(value=self.pid, field="pid")
        require_nonnegative(value=self.uid, field="uid")
        require_ports(values=self.listen_ports, field="listen_ports")
        if self.category is Category.PROJECT:
            raise ValueError("category PROJECT is only valid for groups")
        require_protected_actions(category=self.category, actions=self.actions)

    @property
    def protection(self) -> Protection:
        return protection_of(category=self.category)


@dataclass(frozen=True, slots=True)
class ContainerMember(ImmutableModel):
    id: str
    name: str
    image: str
    state: str
    memory: MemoryUse
    mounts: tuple[Mount, ...]
    activity: ActivityAssessment
    actions: tuple[ActionOffer, ...]

    @property
    def protection(self) -> Protection:
        return protection_of(category=Category.CONTAINER)


Member = ProcessMember | ContainerMember


@dataclass(frozen=True, slots=True)
class GroupGrowth(ImmutableModel):
    """A sustained rise of a group's memory: ``delta_bytes`` gained over ``span_s`` seconds."""

    delta_bytes: int
    span_s: int

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_bytes(value=self.delta_bytes, field="delta_bytes")
        if self.delta_bytes == 0:
            raise ValueError("delta_bytes must be positive")
        if type(self.span_s) is not int or self.span_s <= 0:
            raise ValueError("span_s must be a positive integer number of seconds")


@dataclass(frozen=True, slots=True)
class Group(ImmutableModel):
    id: GroupId
    name: str
    category: Category
    activity: ActivityAssessment
    memory: MemoryUse
    ports: tuple[int, ...]
    primary_action: ActionOffer | None
    ignored: bool
    snoozed_until: datetime | None
    explanation: str
    compose_project: str | None
    members: tuple[Member, ...]
    growth: GroupGrowth | None = None

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_ports(values=self.ports, field="ports")
        require_protected_actions(category=self.category, actions=self.actions)

    @property
    def protection(self) -> Protection:
        return protection_of(category=self.category)

    @property
    def actions(self) -> tuple[ActionOffer, ...]:
        primary = (self.primary_action,) if self.primary_action is not None else ()
        return primary + tuple(action for member in self.members for action in member.actions)


@dataclass(frozen=True, slots=True)
class DockerStatus(ImmutableModel):
    available: bool
    error: str | None

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        if self.available != (self.error is None) or self.error == "":
            raise ValueError("error must be populated exactly when Docker is unavailable")


@dataclass(frozen=True, slots=True)
class ProtectedSummaryItem(ImmutableModel):
    label: str
    memory: int
    reason: str

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_bytes(value=self.memory, field="memory")


@dataclass(frozen=True, slots=True)
class Snapshot(ImmutableModel):
    taken_at: datetime
    monitor_started_at: datetime
    memory: MemorySummary
    disk: DiskUsage
    reclaimable_now: Reclaimable
    pressure: Pressure
    docker: DockerStatus
    groups: tuple[Group, ...]
    protected_summary: tuple[ProtectedSummaryItem, ...]

    def __post_init__(self) -> None:
        ImmutableModel.__post_init__(self)
        require_aware(value=self.taken_at, field="taken_at")
        require_aware(value=self.monitor_started_at, field="monitor_started_at")
        if self.taken_at < self.monitor_started_at:
            raise ValueError("taken_at must not precede monitor_started_at")
        ids = tuple(group.id for group in self.groups)
        if len(ids) != len(set(ids)):
            raise ValueError("groups must have unique ids")
