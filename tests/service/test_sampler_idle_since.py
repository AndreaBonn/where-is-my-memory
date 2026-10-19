from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from tests.core.helpers import process
from tests.service.sampler_helpers import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.config import Config
from wimm.model.enums import ActivityState

STEP_S = 30
WINDOW_S = 300


def _at(*, seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


def test_idle_since_is_the_last_active_cycle_of_this_session(tmp_path: Path) -> None:
    # Active for 10 minutes after the monitor started, then still: the idle duration must
    # count from the last active cycle, not from the monitor start.
    sampler = make_sampler(tmp_path=tmp_path)
    sampler.apply_config(config=Config(activity_window_s=WINDOW_S, sample_interval_s=STEP_S))
    records = [process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=0)]
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=tuple(records))
    )
    last_active_s = 600
    member = None
    for second in range(0, last_active_s + WINDOW_S + 4 * STEP_S, STEP_S):
        busy = 0 < second <= last_active_s
        records[:] = [
            replace(records[0], cpu_time_s=(records[0].cpu_time_s or 0) + (3 if busy else 0))
        ]
        sampler.clock = partial(_at, seconds=second)
        member = sampler.run_cycle().groups[0].members[0]

    assert member is not None
    assert member.activity.state is ActivityState.IDLE
    assert member.activity.since == NOW + timedelta(seconds=last_active_s)
