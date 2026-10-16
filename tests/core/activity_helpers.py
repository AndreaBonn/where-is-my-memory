from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from wimm.core.activity import ActivityConfig, ActivityInputs, EntitySample
from wimm.core.activity_model import Quadruple
from wimm.model.enums import Category

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
INTERVAL = 30
WINDOW = 1800
CONFIG = ActivityConfig(
    window_s=WINDOW, interval_s=INTERVAL, cpu_threshold_pct=1.0, net_threshold_bps=700.0
)
QUAD: Quadruple = ("127.0.0.1", 5173, "127.0.0.1", 40000)
OTHER_QUAD: Quadruple = ("127.0.0.1", 5173, "127.0.0.1", 40001)
LONG_AGO = NOW - timedelta(days=10)
FULL = [-WINDOW + step * INTERVAL for step in range(WINDOW // INTERVAL + 1)]


def at(offset_s: float) -> datetime:
    return NOW + timedelta(seconds=offset_s)


def sample(
    offset_s: float,
    *,
    cpu_time_s: float | None = 0.0,
    connections: frozenset[Quadruple] | None = frozenset(),
    net_bytes: int | None = None,
    foreground: bool | None = None,
) -> EntitySample:
    return EntitySample(
        taken_at=at(offset_s),
        cpu_time_s=cpu_time_s,
        connections=connections,
        net_bytes=net_bytes,
        foreground=foreground,
    )


def cpu_series(
    offsets: Iterable[float], *, active_at: Iterable[float] = (), idle_cpu_step: float = 0.0
) -> tuple[EntitySample, ...]:
    """Samples whose CPU grows by 30 s (100% of a core) at ``active_at`` offsets."""
    active = set(active_at)
    total = 0.0
    result = []
    for offset in offsets:
        total += 30.0 if offset in active else idle_cpu_step
        result.append(sample(offset, cpu_time_s=total))
    return tuple(result)


def inputs(
    history: tuple[EntitySample, ...],
    *,
    category: Category = Category.DEV_PROCESS,
    now: datetime = NOW,
    created_at: datetime = LONG_AGO,
    persisted_last_active: datetime | None = None,
    server_ports: frozenset[int] = frozenset(),
) -> ActivityInputs:
    return ActivityInputs(
        category=category,
        history=history,
        now=now,
        created_at=created_at,
        monitor_started_at=NOW - timedelta(hours=3),
        persisted_last_active=persisted_last_active,
        server_ports=server_ports,
    )
