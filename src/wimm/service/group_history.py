from array import array
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from time import monotonic

from wimm.core import constants as c
from wimm.core.growth import GrowthTrend, growth_trend
from wimm.model.enums import GroupId
from wimm.model.snapshot import Group

MAX_POINTS = c.GROWTH_WINDOW_S // c.GROWTH_SAMPLE_INTERVAL_S + 1


class _Series:
    """Timestamps and byte counts of one group in two typed arrays (8 bytes a value)."""

    def __init__(self) -> None:
        self.times = array("d")
        self.values = array("q")

    def add(self, *, at: float, value: int) -> None:
        self.times.append(at)
        self.values.append(value)
        if len(self.times) > MAX_POINTS:
            del self.times[0]
            del self.values[0]


class GroupHistory:
    """In-RAM memory history of each group: a point every ``GROWTH_SAMPLE_INTERVAL_S``.

    The cadence follows a steady clock, so a wall clock that jumps back does not stall it;
    the wall clock only stamps the points. A cycle shorter than the interval records
    nothing. Groups absent from the snapshot are forgotten. Not thread-safe by design:
    only the sampler worker calls it.
    """

    def __init__(
        self, *, clock: Callable[[], datetime], monotonic: Callable[[], float] = monotonic
    ) -> None:
        self._clock = clock
        self._steady = monotonic
        self._series: dict[GroupId, _Series] = {}
        self._next_due: float | None = None

    def record(self, *, groups: Iterable[Group]) -> None:
        tick = self._steady()
        if self._next_due is not None and tick < self._next_due:
            return
        self._next_due = tick + c.GROWTH_SAMPLE_INTERVAL_S
        now = self._clock().timestamp()
        used = {group.id: group.memory.used for group in groups}
        self._series = {gid: self._series.get(gid, _Series()) for gid in used}
        for gid, value in used.items():
            self._series[gid].add(at=now, value=value)

    def point_count(self, *, group_id: GroupId) -> int:
        series = self._series.get(group_id)
        return 0 if series is None else len(series.times)

    def growth_for(self, *, group_id: GroupId) -> GrowthTrend | None:
        """The sustained growth of a group, or None when it is flat, young or unknown."""
        series = self._series.get(group_id)
        if series is None:
            return None
        points = (
            (datetime.fromtimestamp(at, tz=UTC), value)
            for at, value in zip(series.times, series.values, strict=True)
        )
        return growth_trend(points=points, now=self._clock())
