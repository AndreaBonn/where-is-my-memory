import tracemalloc
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.core.helpers import group, process
from tests.service.service_helpers import FixedClock
from tests.service.test_sampler import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.core import constants as c
from wimm.model.enums import GroupId
from wimm.model.memory import MemoryUse
from wimm.model.snapshot import Group
from wimm.service.group_history import GroupHistory

START = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
MIB = 1024 * 1024
MEMORY_BUDGET_BYTES = 2 * 1024 * 1024
GROUP_COUNT = 1000


def used_group(*, group_id: str, used: int) -> Group:
    return replace(group(), id=GroupId(group_id), memory=MemoryUse(used=used, reclaimable=0))


def history_on(*, clock: FixedClock) -> GroupHistory:
    """A history whose steady clock follows the fake wall clock, until a test splits them."""
    return GroupHistory(clock=clock, monotonic=lambda: (clock.now - START).total_seconds())


def feed(*, history: GroupHistory, clock: FixedClock, seconds: int, used: int) -> None:
    clock.now = START + timedelta(seconds=seconds)
    history.record(groups=[used_group(group_id="g1", used=used)])


def test_record_samples_every_ten_minutes_not_every_cycle() -> None:
    clock = FixedClock(START)
    history = history_on(clock=clock)
    # a 30 s cycle for 3 hours, memory rising 1 MiB per cycle
    for cycle in range(361):
        feed(history=history, clock=clock, seconds=30 * cycle, used=cycle * MIB)

    assert history.point_count(group_id=GroupId("g1")) == 19


def test_record_keeps_only_the_last_three_hours() -> None:
    clock = FixedClock(START)
    history = history_on(clock=clock)
    for index in range(40):
        feed(history=history, clock=clock, seconds=600 * index, used=index * MIB)

    assert history.point_count(group_id=GroupId("g1")) == c.GROWTH_WINDOW_S // 600 + 1


def test_record_drops_groups_missing_from_the_snapshot() -> None:
    clock = FixedClock(START)
    history = history_on(clock=clock)
    history.record(groups=[used_group(group_id="a", used=1), used_group(group_id="b", used=1)])
    clock.now = START + timedelta(seconds=600)
    history.record(groups=[used_group(group_id="a", used=2)])

    assert history.point_count(group_id=GroupId("a")) == 2
    assert history.point_count(group_id=GroupId("b")) == 0


def test_growth_for_reports_a_sustained_rise() -> None:
    clock = FixedClock(START)
    history = history_on(clock=clock)
    for index in range(13):
        feed(history=history, clock=clock, seconds=600 * index, used=(1000 + 40 * index) * MIB)

    trend = history.growth_for(group_id=GroupId("g1"))

    assert trend is not None
    assert trend.delta_bytes == 360 * MIB
    assert trend.span_s == 7200


def test_growth_for_flat_unknown_and_young_groups_is_none() -> None:
    clock = FixedClock(START)
    history = history_on(clock=clock)
    for index in range(18):
        feed(history=history, clock=clock, seconds=600 * index, used=1500 * MIB)

    assert history.growth_for(group_id=GroupId("g1")) is None
    assert history.growth_for(group_id=GroupId("unknown")) is None


def test_thousand_groups_for_three_hours_stay_under_two_megabytes() -> None:
    clock = FixedClock(START)
    history = history_on(clock=clock)
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        for index in range(c.GROWTH_WINDOW_S // 600 + 1):
            clock.now = START + timedelta(seconds=600 * index)
            history.record(
                groups=[
                    used_group(group_id=f"group-{n:04d}", used=(500 + index + n) * MIB)
                    for n in range(GROUP_COUNT)
                ]
            )
        after, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert history.point_count(group_id=GroupId("group-0999")) == 19
    assert after - before < MEMORY_BUDGET_BYTES


def test_sampler_cycles_feed_the_group_history_every_ten_minutes(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(
            data=(process(pid=20, name="node", cmdline=("node",), create_time=1),)
        ),
    )
    clock = FixedClock(NOW)
    sampler.clock = clock
    sampler.group_history = history_on(clock=clock)
    for seconds in (0, 30, 60, 600, 630):
        clock.now = NOW + timedelta(seconds=seconds)
        snapshot = sampler.run_cycle()

    group_id = snapshot.groups[0].id
    assert sampler.group_history.point_count(group_id=group_id) == 2


class Steady:
    """A settable steady clock, independent from the wall clock."""

    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds


def test_record_keeps_sampling_when_the_wall_clock_goes_back_an_hour() -> None:
    wall, steady = FixedClock(START), Steady()
    history = GroupHistory(clock=wall, monotonic=steady)
    history.record(groups=[used_group(group_id="g1", used=MIB)])
    wall.now = START - timedelta(hours=1)
    steady.seconds += c.GROWTH_SAMPLE_INTERVAL_S
    history.record(groups=[used_group(group_id="g1", used=2 * MIB)])
    steady.seconds += c.GROWTH_SAMPLE_INTERVAL_S
    history.record(groups=[used_group(group_id="g1", used=3 * MIB)])

    assert history.point_count(group_id=GroupId("g1")) == 3


def test_record_skips_a_cycle_shorter_than_the_interval_even_if_the_wall_clock_jumps() -> None:
    wall, steady = FixedClock(START), Steady()
    history = GroupHistory(clock=wall, monotonic=steady)
    history.record(groups=[used_group(group_id="g1", used=MIB)])
    wall.now = START + timedelta(hours=2)
    steady.seconds += 30
    history.record(groups=[used_group(group_id="g1", used=2 * MIB)])

    assert history.point_count(group_id=GroupId("g1")) == 1
