from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from tests.core.helpers import process
from tests.service.test_sampler import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.config import Config
from wimm.model.enums import ActivityState, Protection
from wimm.model.raw import RawProcess
from wimm.service.sampler import Sampler


def _cpu_burning_sampler(*, tmp_path: Path) -> tuple[Sampler, list[RawProcess]]:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=0)
    records = [proc]
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=tuple(records))
    )
    sampler.run_cycle()
    return sampler, records


def _next_cycle_state(
    *, sampler: Sampler, records: list[RawProcess], seconds: int
) -> ActivityState:
    """Burn 3 CPU-seconds (10% of a 30 s step) and return the process verdict."""
    records[:] = [replace(records[0], cpu_time_s=(records[0].cpu_time_s or 0) + 3)]
    sampler.clock = lambda: NOW + timedelta(seconds=seconds)
    member = sampler.run_cycle().groups[0].members[0]
    return member.activity.state


def test_apply_config_changes_the_cpu_threshold_of_the_next_cycle(tmp_path: Path) -> None:
    sampler, records = _cpu_burning_sampler(tmp_path=tmp_path)
    assert _next_cycle_state(sampler=sampler, records=records, seconds=30) is ActivityState.ACTIVE
    sampler.apply_config(config=Config(cpu_active_threshold_pct=20))
    assert (
        _next_cycle_state(sampler=sampler, records=records, seconds=60) is not ActivityState.ACTIVE
    )


def test_apply_config_with_unchanged_threshold_keeps_the_verdict(tmp_path: Path) -> None:
    sampler, records = _cpu_burning_sampler(tmp_path=tmp_path)
    assert _next_cycle_state(sampler=sampler, records=records, seconds=30) is ActivityState.ACTIVE
    sampler.apply_config(config=Config())
    assert _next_cycle_state(sampler=sampler, records=records, seconds=60) is ActivityState.ACTIVE


def test_apply_config_hides_a_newly_protected_name_in_the_next_cycle(tmp_path: Path) -> None:
    sampler, _ = _cpu_burning_sampler(tmp_path=tmp_path)
    assert sampler.run_cycle().groups[0].members[0].protection is Protection.ACTIONABLE
    sampler.apply_config(config=Config(extra_protected_names=("node",)))
    assert sampler.run_cycle().groups == ()


def test_apply_config_resizes_the_history_to_the_new_window(tmp_path: Path) -> None:
    sampler, records = _cpu_burning_sampler(tmp_path=tmp_path)
    sampler.apply_config(config=Config(activity_window_s=300, sample_interval_s=30))
    for cycle in range(1, 30):
        _next_cycle_state(sampler=sampler, records=records, seconds=30 * cycle)
    assert len(sampler.history.history_for(key=(20, 1.0))) == 11


def test_apply_config_opens_ssh_session_processes_in_the_next_cycle(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    ssh_scope = "/user.slice/user-1000.slice/session-5.scope"
    proc = process(pid=20, name="node", cmdline=("node",), cgroup=ssh_scope)
    sshd = process(pid=10, name="sshd-session", cgroup=ssh_scope)
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(sshd, proc))
    )
    assert sampler.run_cycle().groups == ()
    sampler.apply_config(config=Config(remote_sessions_actionable=True))
    groups = sampler.run_cycle().groups
    member = next(m for g in groups for m in g.members if getattr(m, "pid", None) == 20)
    assert member.protection is Protection.ACTIONABLE
