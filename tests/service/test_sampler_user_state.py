from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from tests.core.helpers import process
from tests.service.test_sampler import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.core.assemble import UserState
from wimm.service.sampler import Sampler


def _sampler_with_one_group(*, tmp_path: Path) -> Sampler:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=10)
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(proc,))
    )
    return sampler


def test_apply_user_state_marks_the_group_in_the_next_snapshot_and_can_be_undone(
    tmp_path: Path,
) -> None:
    sampler = _sampler_with_one_group(tmp_path=tmp_path)
    group = sampler.run_cycle().groups[0]
    assert (group.ignored, group.snoozed_until) == (False, None)
    until = NOW + timedelta(hours=1)
    sampler.apply_user_state(
        user=UserState(ignored=frozenset({group.id}), snoozed_until={group.id: until})
    )
    marked = sampler.run_cycle().groups[0]
    assert (marked.ignored, marked.snoozed_until) == (True, until)
    sampler.apply_user_state(user=UserState())
    restored = sampler.run_cycle().groups[0]
    assert (restored.ignored, restored.snoozed_until) == (False, None)


def test_a_snooze_already_expired_is_not_applied(tmp_path: Path) -> None:
    sampler = _sampler_with_one_group(tmp_path=tmp_path)
    group = sampler.run_cycle().groups[0]
    sampler.apply_user_state(user=UserState(snoozed_until={group.id: NOW - timedelta(seconds=1)}))
    assert sampler.run_cycle().groups[0].snoozed_until is None
