from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from wimm.config import Config
from wimm.model.enums import GroupId
from wimm.model.snapshot import Snapshot

Episode = tuple[GroupId, datetime]


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    """A notification to show; ``group_id`` feeds the open/snooze actions (None if no group)."""

    id: str
    title: str
    body: str
    group_id: GroupId | None


@dataclass(frozen=True, slots=True)
class NotificationState:
    """What was already notified: idle episodes, last pressure per kind, send times."""

    episodes: frozenset[Episode] = frozenset()
    pressure_sent: Mapping[str, datetime] = field(default_factory=lambda: MappingProxyType({}))
    sent_at: tuple[datetime, ...] = ()
    oom_kills_seen: int | None = None


@dataclass(frozen=True, slots=True)
class NotifyRequest:
    """Everything the rules need, clock included; ``muted_until`` is the global silence."""

    snapshot: Snapshot
    config: Config
    state: NotificationState
    now: datetime
    muted_until: datetime | None = None
    oom_kills: int | None = None


@dataclass(frozen=True, slots=True)
class NotifyResult:
    intents: tuple[NotificationIntent, ...]
    state: NotificationState
