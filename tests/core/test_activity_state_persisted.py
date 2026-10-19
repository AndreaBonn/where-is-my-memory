from datetime import timedelta

from wimm.core.activity import (
    assess_activity,
)
from wimm.model.enums import ActivityState

from .activity_helpers import (
    CONFIG,
    FULL,
    NOW,
    WINDOW,
    at,
    cpu_series,
    inputs,
)


def test_restart_with_persisted_activity_is_idle_immediately() -> None:
    persisted = NOW - timedelta(hours=3)
    history = cpu_series([-90, -60, -30, 0])
    result = assess_activity(inputs=inputs(history, persisted_last_active=persisted), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.IDLE, persisted)
    assert result.reason == (
        "inattivo da 3 h; ultima attività registrata prima del riavvio, in osservazione da 1 minuto"
    )


def test_recent_persisted_activity_is_not_idle_before_a_window_has_passed() -> None:
    persisted = NOW - timedelta(minutes=10)
    history = cpu_series([-60, -30, 0])
    result = assess_activity(inputs=inputs(history, persisted_last_active=persisted), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.UNKNOWN, None)
    older = NOW - timedelta(seconds=WINDOW)
    result = assess_activity(inputs=inputs(history, persisted_last_active=older), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.IDLE, older)


def test_restart_persisted_idle_turns_active_on_first_active_sample() -> None:
    persisted = NOW - timedelta(hours=3)
    history = cpu_series([-90, -60, -30, 0], active_at={-30})
    result = assess_activity(inputs=inputs(history, persisted_last_active=persisted), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-30))


def test_persisted_before_process_start_is_clamped_to_process_start() -> None:
    created = NOW - timedelta(hours=1)
    persisted = NOW - timedelta(hours=5)
    result = assess_activity(
        inputs=inputs(cpu_series([0]), created_at=created, persisted_last_active=persisted),
        config=CONFIG,
    )
    assert (result.state, result.since) == (ActivityState.IDLE, created)


def test_persisted_value_wins_over_monitor_start_when_history_covers() -> None:
    persisted = NOW - timedelta(hours=2)
    result = assess_activity(
        inputs=inputs(cpu_series(FULL), persisted_last_active=persisted), config=CONFIG
    )
    assert (result.state, result.since) == (ActivityState.IDLE, persisted)
    assert "cioè da quando il monitor è partito" not in result.reason


def test_without_persisted_value_short_history_stays_unknown() -> None:
    result = assess_activity(inputs=inputs(cpu_series([-30, 0])), config=CONFIG)
    assert result.state is ActivityState.UNKNOWN
