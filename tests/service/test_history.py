from datetime import UTC, datetime, timedelta

from wimm.core.activity import ActivityConfig, EntityKind, EntitySample, sample_is_active
from wimm.service.history import SampleHistory

START = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
CONFIG = ActivityConfig(
    window_s=1800, interval_s=30, cpu_threshold_pct=1.0, net_threshold_bps=700.0
)
QUAD = ("127.0.0.1", 5173, "127.0.0.1", 40000)
PROCESS_KEY = (4242, 1760000000.5)
CONTAINER_KEY = "a1b2c3d4"


def sample(cycle: int) -> EntitySample:
    return EntitySample(taken_at=START + timedelta(seconds=30 * cycle), cpu_time_s=float(cycle))


def new_history() -> SampleHistory:
    return SampleHistory(window_s=1800, interval_s=30)


def test_history_for_unknown_key_is_empty() -> None:
    assert new_history().history_for(key=PROCESS_KEY) == ()


def test_samples_are_kept_oldest_first_as_an_immutable_tuple() -> None:
    history = new_history()
    for cycle in range(3):
        history.append(cycle_samples={PROCESS_KEY: sample(cycle)})
    stored = history.history_for(key=PROCESS_KEY)
    assert isinstance(stored, tuple)
    assert [s.cpu_time_s for s in stored] == [0.0, 1.0, 2.0]


def test_ring_keeps_window_over_interval_plus_one_samples() -> None:
    history = new_history()
    for cycle in range(70):
        history.append(cycle_samples={PROCESS_KEY: sample(cycle)})
    stored = history.history_for(key=PROCESS_KEY)
    assert len(stored) == 61
    assert (stored[0].cpu_time_s, stored[-1].cpu_time_s) == (9.0, 69.0)


def test_ring_length_follows_configured_window_and_interval() -> None:
    history = SampleHistory(window_s=300, interval_s=10)
    for cycle in range(100):
        history.append(cycle_samples={CONTAINER_KEY: sample(cycle)})
    assert len(history.history_for(key=CONTAINER_KEY)) == 31


def test_identity_includes_create_time_so_pid_reuse_starts_fresh() -> None:
    history = new_history()
    history.append(cycle_samples={(4242, 1.0): sample(0), (4242, 2.0): sample(0)})
    history.append(cycle_samples={(4242, 2.0): sample(1)})
    assert len(history.history_for(key=(4242, 1.0))) == 1
    assert len(history.history_for(key=(4242, 2.0))) == 2


def test_entity_absent_for_three_cycles_is_removed() -> None:
    history = new_history()
    history.append(cycle_samples={PROCESS_KEY: sample(0), CONTAINER_KEY: sample(0)})
    for cycle in (1, 2):
        history.append(cycle_samples={CONTAINER_KEY: sample(cycle)})
        assert len(history.history_for(key=PROCESS_KEY)) == 1
    history.append(cycle_samples={CONTAINER_KEY: sample(3)})
    assert history.history_for(key=PROCESS_KEY) == ()
    assert len(history.history_for(key=CONTAINER_KEY)) == 4


def test_entity_back_after_two_missed_cycles_keeps_history_and_resets_counter() -> None:
    history = new_history()
    history.append(cycle_samples={PROCESS_KEY: sample(0)})
    history.append(cycle_samples={})
    history.append(cycle_samples={})
    history.append(cycle_samples={PROCESS_KEY: sample(3)})
    assert len(history.history_for(key=PROCESS_KEY)) == 2
    history.append(cycle_samples={})
    history.append(cycle_samples={})
    assert len(history.history_for(key=PROCESS_KEY)) == 2


def test_connection_present_in_two_consecutive_stored_samples_is_not_new() -> None:
    history = new_history()
    for cycle in range(2):
        quiet = EntitySample(
            taken_at=START + timedelta(seconds=30 * cycle),
            cpu_time_s=0.0,
            connections=frozenset({QUAD}),
        )
        history.append(cycle_samples={PROCESS_KEY: quiet})
    prev, curr = history.history_for(key=PROCESS_KEY)
    assert not sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_new_connection_with_flat_cpu_in_stored_samples_is_active() -> None:
    history = new_history()
    other = ("127.0.0.1", 5173, "127.0.0.1", 40001)
    for cycle, connections in enumerate((frozenset({QUAD}), frozenset({QUAD, other}))):
        flat = EntitySample(
            taken_at=START + timedelta(seconds=30 * cycle),
            cpu_time_s=0.0,
            connections=connections,
        )
        history.append(cycle_samples={PROCESS_KEY: flat})
    prev, curr = history.history_for(key=PROCESS_KEY)
    assert sample_is_active(prev=prev, curr=curr, kind=EntityKind.SERVER, config=CONFIG)


def test_resize_to_a_smaller_ring_keeps_the_latest_samples() -> None:
    history = new_history()
    for cycle in range(61):
        history.append(cycle_samples={PROCESS_KEY: sample(cycle)})
    history.resize(window_s=300, interval_s=30)
    stored = history.history_for(key=PROCESS_KEY)
    assert len(stored) == 11
    assert (stored[0].cpu_time_s, stored[-1].cpu_time_s) == (50.0, 60.0)


def test_resize_to_a_larger_ring_keeps_samples_and_grows_capacity() -> None:
    history = SampleHistory(window_s=60, interval_s=30)
    for cycle in range(3):
        history.append(cycle_samples={PROCESS_KEY: sample(cycle)})
    history.resize(window_s=300, interval_s=30)
    for cycle in range(3, 20):
        history.append(cycle_samples={PROCESS_KEY: sample(cycle)})
    stored = history.history_for(key=PROCESS_KEY)
    assert len(stored) == 11
    assert (stored[0].cpu_time_s, stored[-1].cpu_time_s) == (9.0, 19.0)


def test_resize_with_the_same_dimensions_changes_nothing() -> None:
    history = new_history()
    for cycle in range(5):
        history.append(cycle_samples={PROCESS_KEY: sample(cycle)})
    before = history.history_for(key=PROCESS_KEY)
    history.resize(window_s=1800, interval_s=30)
    assert history.history_for(key=PROCESS_KEY) == before
    assert len(before) == 5
