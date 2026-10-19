from dataclasses import replace
from pathlib import Path

from tests.core.helpers import process
from tests.service.sampler_helpers import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.core.growth import GrowthTrend
from wimm.model.enums import GroupId
from wimm.model.snapshot import GroupGrowth
from wimm.service.group_history import GroupHistory
from wimm.service.sampler import Sampler

TWO_HOURS_S = 7200
GAINED = 620_000_000


class FakeHistory(GroupHistory):
    """A history that answers a canned trend for chosen groups."""

    def __init__(self, *, trends: dict[str, GrowthTrend]) -> None:
        super().__init__(clock=lambda: NOW)
        self.trends = trends

    def growth_for(self, *, group_id: GroupId) -> GrowthTrend | None:
        return self.trends.get(group_id)


def sampler_with(*, tmp_path: Path) -> Sampler:
    sampler = make_sampler(tmp_path=tmp_path)
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(
            data=(process(pid=20, name="node", cmdline=("node",), create_time=1),)
        ),
    )
    return sampler


def test_sampler_copies_the_history_trend_into_the_group(tmp_path: Path) -> None:
    sampler = sampler_with(tmp_path=tmp_path)
    group_id = sampler.run_cycle().groups[0].id
    trend = GrowthTrend(delta_bytes=GAINED, span_s=TWO_HOURS_S)
    sampler.group_history = FakeHistory(trends={group_id: trend})

    snapshot = sampler.run_cycle()

    assert snapshot.groups[0].growth == GroupGrowth(delta_bytes=GAINED, span_s=TWO_HOURS_S)


def test_sampler_leaves_growth_empty_when_the_history_sees_none(tmp_path: Path) -> None:
    sampler = sampler_with(tmp_path=tmp_path)
    sampler.group_history = FakeHistory(trends={})

    assert sampler.run_cycle().groups[0].growth is None
