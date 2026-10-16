from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from .activity_model import (
    MEASURABLE_KINDS,
    ActivityConfig,
    ActivityInputs,
    EntityKind,
    EntitySample,
)

PERCENT = 100.0


@dataclass(frozen=True, slots=True)
class Step:
    prev: EntitySample
    curr: EntitySample
    active: bool


def elapsed_s(*, prev: EntitySample, curr: EntitySample) -> float:
    return (curr.taken_at - prev.taken_at).total_seconds()


def _rate(*, before: float | None, after: float | None, elapsed: float) -> float | None:
    if before is None or after is None or elapsed <= 0 or after < before:
        return None
    return (after - before) / elapsed


def cpu_percent(*, prev: EntitySample, curr: EntitySample) -> float | None:
    """Mean CPU between two samples in % of one core; None if not measurable."""
    rate = _rate(
        before=prev.cpu_time_s, after=curr.cpu_time_s, elapsed=elapsed_s(prev=prev, curr=curr)
    )
    return None if rate is None else rate * PERCENT


def net_rate_bps(*, prev: EntitySample, curr: EntitySample) -> float | None:
    """Mean network rate in bytes/s between two samples; None if not measurable."""
    return _rate(
        before=prev.net_bytes, after=curr.net_bytes, elapsed=elapsed_s(prev=prev, curr=curr)
    )


def sample_is_active(
    *, prev: EntitySample, curr: EntitySample, kind: EntityKind, config: ActivityConfig
) -> bool:
    """Whether ``curr`` shows activity relative to ``prev`` (5.4, first table).

    Thresholds are strict: a mean exactly equal to the threshold is not activity.
    """
    if kind not in MEASURABLE_KINDS or elapsed_s(prev=prev, curr=curr) <= 0:
        return False
    cpu = cpu_percent(prev=prev, curr=curr)
    if cpu is not None and cpu > config.cpu_threshold_pct:
        return True
    if kind is EntityKind.SERVER:
        if prev.connections is None or curr.connections is None:
            return False
        return bool(curr.connections - prev.connections)
    if kind is EntityKind.CONTAINER:
        rate = net_rate_bps(prev=prev, curr=curr)
        return rate is not None and rate > config.net_threshold_bps
    return False


def build_steps(*, inputs: ActivityInputs, kind: EntityKind, config: ActivityConfig) -> list[Step]:
    cutoff = inputs.now - timedelta(seconds=config.window_s)
    return [
        Step(
            prev=prev,
            curr=curr,
            active=sample_is_active(prev=prev, curr=curr, kind=kind, config=config),
        )
        for prev, curr in pairwise(inputs.history)
        if curr.taken_at >= cutoff
    ]


def current_run_start(*, steps: Sequence[Step]) -> datetime | None:
    """Time of the first sample of the active run that ends at the latest active sample."""
    last = next((i for i in range(len(steps) - 1, -1, -1) if steps[i].active), None)
    if last is None:
        return None
    first = last
    while first > 0 and steps[first - 1].active:
        first -= 1
    return steps[first].curr.taken_at


def window_averages(*, steps: Sequence[Step]) -> tuple[float | None, float | None]:
    """Window-wide (CPU %, network B/s) means, weighted by interval length."""
    cpu_work = cpu_time = net_work = net_time = 0.0
    for step in steps:
        elapsed = elapsed_s(prev=step.prev, curr=step.curr)
        cpu = cpu_percent(prev=step.prev, curr=step.curr)
        net = net_rate_bps(prev=step.prev, curr=step.curr)
        if cpu is not None:
            cpu_work, cpu_time = cpu_work + cpu * elapsed, cpu_time + elapsed
        if net is not None:
            net_work, net_time = net_work + net * elapsed, net_time + elapsed
    return (
        cpu_work / cpu_time if cpu_time else None,
        net_work / net_time if net_time else None,
    )


def open_port(*, server_ports: frozenset[int], steps: Sequence[Step]) -> int | None:
    """Server port of a connection open across the last step, if any.

    A connection that closed earlier in the window is history, not a forgotten tab.
    """
    if not steps or steps[-1].prev.connections is None or steps[-1].curr.connections is None:
        return None
    persistent = steps[-1].prev.connections & steps[-1].curr.connections
    if not persistent:
        return None
    _, local_port, _, remote_port = min(persistent)
    return remote_port if remote_port in server_ports else local_port
