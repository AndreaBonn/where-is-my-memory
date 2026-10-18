from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import median

from . import constants as c


@dataclass(frozen=True, slots=True)
class GrowthTrend:
    """A sustained rise: ``delta_bytes`` gained over ``span_s`` seconds."""

    delta_bytes: int
    span_s: int


def _significant_falls(*, values: list[int]) -> int:
    """Sum of the falls between consecutive samples that exceed the jitter floor."""
    drops = (before - after for before, after in pairwise(values))
    return sum(drop for drop in drops if drop > c.GROWTH_NOISE_BYTES)


def growth_trend(*, points: Iterable[tuple[datetime, int]], now: datetime) -> GrowthTrend | None:
    """Tell whether a group's memory grows steadily over the last ``GROWTH_WINDOW_S``.

    Points are sorted by time; those in the future or older than the window are ignored.
    The start and the end of the series are the medians of its first and last third, so a
    single spike moves neither. The series grows when the end exceeds the start by at least
    ``GROWTH_MIN_BYTES`` and ``GROWTH_MIN_RATIO`` of the start, spanning at least
    ``GROWTH_MIN_SPAN_S`` over ``GROWTH_MIN_POINTS`` points, and the falls along the way
    stay under ``GROWTH_MAX_DROP_FRACTION`` of the gain (a cache that empties is not a leak).
    Falls of ``GROWTH_NOISE_BYTES`` or less between two samples are jitter and do not count.
    Returns None when it does not grow or the series is too short.
    """
    oldest = now - timedelta(seconds=c.GROWTH_WINDOW_S)
    ordered = sorted((p for p in points if oldest <= p[0] <= now), key=lambda p: p[0])
    if len(ordered) < c.GROWTH_MIN_POINTS:
        return None
    span_s = int((ordered[-1][0] - ordered[0][0]).total_seconds())
    if span_s < c.GROWTH_MIN_SPAN_S:
        return None
    values = [value for _, value in ordered]
    edge = len(values) // c.GROWTH_EDGE_PARTS
    start, end = median(values[:edge]), median(values[-edge:])
    delta = end - start
    if delta < c.GROWTH_MIN_BYTES or delta < c.GROWTH_MIN_RATIO * start:
        return None
    if _significant_falls(values=values) > c.GROWTH_MAX_DROP_FRACTION * delta:
        return None
    return GrowthTrend(delta_bytes=int(delta), span_s=span_s)
