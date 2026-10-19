from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from tests.core.assemble_helpers import container
from tests.core.helpers import process
from tests.service.sampler_helpers import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.collectors.docker_source import DockerSample
from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment, DockerStatus
from wimm.paths import UserPaths
from wimm.service.history import LastActiveTracker
from wimm.service.sampler import Sampler
from wimm.service.state_store import PersistedState, load_state, save_state

DAY_S = 86400
KEY = (20, 1.0)


def verdict(state: ActivityState, since: datetime | None = None) -> ActivityAssessment:
    return ActivityAssessment(state=state, since=since, reason="r")


def test_active_sample_records_the_end_of_its_activity() -> None:
    tracker = LastActiveTracker(persisted={})
    tracker.observe(key=KEY, assessment=verdict(ActivityState.ACTIVE, NOW), active_at=NOW)
    assert dict(tracker.export(now=NOW, retention_s=DAY_S)) == {KEY: NOW}


def test_idle_keeps_the_last_active_instant_instead_of_advancing_it() -> None:
    tracker = LastActiveTracker(persisted={})
    tracker.observe(key=KEY, assessment=verdict(ActivityState.ACTIVE, NOW), active_at=NOW)
    later = NOW + timedelta(hours=3)
    # an assessed since that differs from the recorded instant: only NOW may survive
    idle_since = NOW + timedelta(hours=1)
    tracker.observe(key=KEY, assessment=verdict(ActivityState.IDLE, idle_since), active_at=None)
    assert tracker.export(now=later, retention_s=DAY_S)[KEY] == NOW


def test_idle_without_history_takes_the_assessed_since() -> None:
    tracker = LastActiveTracker(persisted={})
    since = NOW - timedelta(hours=1)
    tracker.observe(key="c1", assessment=verdict(ActivityState.IDLE, since), active_at=None)
    assert tracker.export(now=NOW, retention_s=DAY_S)["c1"] == since


def test_unknown_changes_nothing_and_active_overrides_persisted() -> None:
    old = NOW - timedelta(hours=9)
    tracker = LastActiveTracker(persisted={KEY: old})
    tracker.observe(key=KEY, assessment=verdict(ActivityState.UNKNOWN), active_at=None)
    assert tracker.export(now=NOW, retention_s=DAY_S)[KEY] == old
    tracker.observe(key=KEY, assessment=verdict(ActivityState.ACTIVE, NOW), active_at=NOW)
    assert tracker.export(now=NOW, retention_s=DAY_S)[KEY] == NOW


def test_unseen_entity_is_forgotten_only_after_the_retention() -> None:
    fresh, stale = NOW - timedelta(seconds=DAY_S - 1), NOW - timedelta(seconds=DAY_S + 1)
    tracker = LastActiveTracker(persisted={"fresh": fresh, "stale": stale, "seen": stale})
    tracker.observe(key="seen", assessment=verdict(ActivityState.UNKNOWN), active_at=None)
    assert set(tracker.export(now=NOW, retention_s=DAY_S)) == {"fresh", "seen"}


def test_restart_through_the_state_file_keeps_the_idle_since(tmp_path: Path) -> None:
    paths = UserPaths(config_dir=tmp_path, state_dir=tmp_path / "wimm", cache_dir=tmp_path)
    cpu = {"seconds": 0.0}
    sampler = make_sampler(tmp_path=tmp_path)
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(
            data=(
                process(
                    pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=cpu["seconds"]
                ),
            )
        ),
    )
    sampler.run_cycle()
    cpu["seconds"] = 3.0
    active_at = NOW + timedelta(seconds=30)
    sampler.clock = lambda: active_at
    assert sampler.run_cycle().groups[0].members[0].activity.state is ActivityState.ACTIVE
    save_state(
        paths=paths,
        state=PersistedState(last_active=sampler.export_last_active()),
    )

    restarted_at = active_at + timedelta(hours=3)
    restored = load_state(paths=paths, now=restarted_at).last_active
    assert restored == {KEY: active_at}
    environment = replace(sampler.environment, persisted_last_active=restored)
    second = Sampler(
        collectors=sampler.collectors,
        environment=environment,
        config=sampler.settings,
        clock=lambda: restarted_at,
    )
    member = second.run_cycle().groups[0].members[0]
    assert member.activity.state is ActivityState.IDLE
    assert member.activity.since == active_at
    assert second.export_last_active()[KEY] == active_at


def test_entities_absent_from_a_cycle_are_not_seen_and_expire() -> None:
    stale = NOW - timedelta(seconds=DAY_S + 1)
    tracker = LastActiveTracker(persisted={"dead": stale, "alive": stale})
    for _ in range(2):
        tracker.begin_cycle()
        tracker.observe(key="alive", assessment=verdict(ActivityState.UNKNOWN), active_at=None)
    assert set(tracker.export(now=NOW, retention_s=DAY_S)) == {"alive"}
    tracker.begin_cycle()
    assert set(tracker.export(now=NOW, retention_s=DAY_S)) == {"alive"}
    tracker.begin_cycle()
    assert set(tracker.export(now=NOW, retention_s=DAY_S)) == set()


def test_a_container_keeps_its_persisted_idle_since_after_a_restart(tmp_path: Path) -> None:
    # F5: a container idle for hours read "non in uso da 25 s" right after the app started,
    # because its creation time was taken to be the monitor start.
    idle_since = NOW - timedelta(hours=3)
    sampler = make_sampler(tmp_path=tmp_path)
    sample = DockerSample(
        status=DockerStatus(available=True, error=None), containers=(container("sigv4"),)
    )
    collectors = replace(sampler.collectors, docker=lambda: CollectorResult(data=sample))
    environment = replace(sampler.environment, persisted_last_active={"id-sigv4": idle_since})
    restarted = Sampler(
        collectors=collectors, environment=environment, config=sampler.settings, clock=lambda: NOW
    )

    member = restarted.run_cycle().groups[0].members[0]

    assert member.activity.state is ActivityState.IDLE
    assert member.activity.since == idle_since
