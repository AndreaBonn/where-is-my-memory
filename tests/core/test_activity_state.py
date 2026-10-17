from dataclasses import replace
from datetime import timedelta

import pytest

from wimm.core.activity import (
    assess_activity,
)
from wimm.model.enums import ActivityState, Category

from .activity_helpers import (
    CONFIG,
    FULL,
    INTERVAL,
    NOW,
    QUAD,
    WINDOW,
    at,
    cpu_series,
    inputs,
)


def test_active_since_is_start_of_current_run() -> None:
    history = cpu_series(FULL, active_at={-600, -570, -540})
    result = assess_activity(inputs=inputs(history), config=CONFIG)
    assert result.state is ActivityState.ACTIVE
    assert result.since == at(-600)
    assert result.reason == "attività rilevata da 10 minuti"


def test_active_run_restarts_after_a_quiet_gap() -> None:
    history = cpu_series(FULL, active_at={-1200, -1170, -300, -270})
    result = assess_activity(inputs=inputs(history), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-300))


def test_one_active_sample_in_a_short_history_is_active() -> None:
    history = cpu_series([-60, -30, 0], active_at={0})
    result = assess_activity(inputs=inputs(history), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(0))


def test_activity_exactly_at_window_start_counts() -> None:
    offsets = [-WINDOW - 30, -WINDOW, *range(-WINDOW + 30, 1, 30)]
    result = assess_activity(inputs=inputs(cpu_series(offsets, active_at={-WINDOW})), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-WINDOW))


def test_activity_just_before_window_start_is_ignored() -> None:
    offsets = [-WINDOW - 31, -WINDOW - 1, *range(-WINDOW + 29, 1, 30)]
    result = assess_activity(
        inputs=inputs(cpu_series(offsets, active_at={-WINDOW - 1})), config=CONFIG
    )
    assert result.state is ActivityState.IDLE


def test_idle_when_window_covered_without_activity() -> None:
    history = cpu_series(FULL, idle_cpu_step=0.0)
    result = assess_activity(inputs=inputs(history), config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert result.since == NOW - timedelta(hours=3)
    assert result.reason == (
        "inattivo da almeno 3 h, cioè da quando il monitor è partito; "
        "CPU media 0,0% negli ultimi 30 minuti"
    )


def test_idle_since_is_process_start_when_newer_than_monitor() -> None:
    created = NOW - timedelta(minutes=45)
    result = assess_activity(inputs=inputs(cpu_series(FULL), created_at=created), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.IDLE, created)
    assert result.reason.startswith("inattivo da 45 minuti; ")


def test_idle_reason_reports_measured_cpu() -> None:
    history = cpu_series(FULL, idle_cpu_step=0.1)  # 0.1 s per 30 s = 0.33%
    result = assess_activity(inputs=inputs(history), config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert "CPU media 0,3%" in result.reason


def test_server_idle_reason_has_no_incoming_connection() -> None:
    inp = inputs(cpu_series(FULL), category=Category.DEV_SERVER, server_ports=frozenset({5173}))
    result = assess_activity(inputs=inp, config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert (
        "nessuna connessione in ingresso e CPU media 0,0% negli ultimi 30 minuti" in result.reason
    )
    assert "browser" not in result.reason


def test_hmr_websocket_open_is_idle_with_forgotten_tab_reason() -> None:
    history = tuple(
        replace(s, cpu_time_s=index * 0.03, connections=frozenset({QUAD}))
        for index, s in enumerate(cpu_series(FULL))
    )
    inp = inputs(history, category=Category.DEV_SERVER, server_ports=frozenset({5173}))
    result = assess_activity(inputs=inp, config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert "CPU media 0,1%" in result.reason
    assert "c'è una connessione aperta da un browser" in result.reason
    assert "localhost:5173" in result.reason


def test_hmr_port_is_found_on_the_remote_side_for_local_clients() -> None:
    client_side = ("127.0.0.1", 40000, "127.0.0.1", 5173)
    history = tuple(replace(s, connections=frozenset({client_side})) for s in cpu_series(FULL))
    inp = inputs(history, category=Category.DEV_SERVER, server_ports=frozenset({5173}))
    assert "localhost:5173" in assess_activity(inputs=inp, config=CONFIG).reason


def test_connection_closed_long_ago_does_not_cite_a_forgotten_tab() -> None:
    history = tuple(
        replace(s, connections=frozenset({QUAD}) if index < 6 else frozenset())
        for index, s in enumerate(cpu_series(FULL))
    )
    inp = inputs(history, category=Category.DEV_SERVER, server_ports=frozenset({5173}))
    result = assess_activity(inputs=inp, config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert "scheda dimenticata" not in result.reason


def test_unmeasured_connections_cycle_gives_no_false_new_connection() -> None:
    history = list(cpu_series(FULL))
    history = [replace(s, connections=frozenset({QUAD})) for s in history]
    history[30] = replace(history[30], connections=None)
    inp = inputs(tuple(history), category=Category.DEV_SERVER, server_ports=frozenset({5173}))
    assert assess_activity(inputs=inp, config=CONFIG).state is ActivityState.IDLE


def test_new_connection_in_window_makes_server_active() -> None:
    history = list(cpu_series(FULL))
    history[-1] = replace(history[-1], connections=frozenset({QUAD}))
    inp = inputs(tuple(history), category=Category.DEV_SERVER)
    result = assess_activity(inputs=inp, config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(0))


def test_short_history_is_unknown_with_elapsed_time() -> None:
    now = at(240)
    history = cpu_series(range(0, 241, INTERVAL))
    result = assess_activity(inputs=inputs(history, now=now), config=CONFIG)
    assert result.state is ActivityState.UNKNOWN
    assert result.since is None
    assert result.reason == "in osservazione da 4 minuti"


def test_empty_history_is_unknown() -> None:
    result = assess_activity(inputs=inputs(()), config=CONFIG)
    assert (result.state, result.reason) == (
        ActivityState.UNKNOWN,
        "in osservazione da meno di 1 minuto",
    )


def test_coverage_tolerates_one_interval_of_jitter() -> None:
    covered = cpu_series([-WINDOW + 30, *range(-WINDOW + 60, 1, 30)])
    short = cpu_series([-WINDOW + 31, *range(-WINDOW + 61, 1, 30)])
    assert assess_activity(inputs=inputs(covered), config=CONFIG).state is ActivityState.IDLE
    assert assess_activity(inputs=inputs(short), config=CONFIG).state is ActivityState.UNKNOWN


@pytest.mark.parametrize("interval", [30, 70, 300, 700])
def test_a_full_ring_reaches_idle_for_any_interval(interval: int) -> None:
    config = replace(CONFIG, interval_s=interval)
    ring_span = WINDOW - WINDOW % interval  # the ring holds window // interval + 1 samples
    history = cpu_series(range(-ring_span, 1, interval))
    result = assess_activity(inputs=inputs(history), config=config)
    assert result.state is ActivityState.IDLE


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


def test_idle_requires_a_measurable_cpu_signal() -> None:
    history = tuple(replace(s, cpu_time_s=None) for s in cpu_series(FULL))
    result = assess_activity(inputs=inputs(history), config=CONFIG)
    assert (result.state, result.reason) == (
        ActivityState.UNKNOWN,
        "CPU non misurabile negli ultimi campioni",
    )


def test_container_idle_reports_network_rate_and_active_via_network() -> None:
    quiet = tuple(replace(s, net_bytes=index * 300) for index, s in enumerate(cpu_series(FULL)))
    inp = inputs(quiet, category=Category.CONTAINER)
    result = assess_activity(inputs=inp, config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert "traffico di rete medio 10 B/s" in result.reason
    busy_bytes = (len(quiet) - 2) * 300 + 30 * 701
    busy = (*quiet[:-1], replace(quiet[-1], net_bytes=busy_bytes))
    result = assess_activity(inputs=replace(inp, history=busy), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(0))


def test_container_without_network_signal_reports_cpu_only() -> None:
    result = assess_activity(
        inputs=inputs(cpu_series(FULL), category=Category.CONTAINER), config=CONFIG
    )
    assert result.state is ActivityState.IDLE
    assert "traffico di rete" not in result.reason


@pytest.mark.parametrize(
    ("category", "reason"),
    [
        (Category.BROWSER, "attività non misurabile per i browser"),
        (Category.TERMINAL, "attività non misurabile per i terminali"),
    ],
)
def test_unmeasurable_categories_are_unknown_even_with_cpu(category: Category, reason: str) -> None:
    history = cpu_series(FULL, active_at=set(FULL))
    result = assess_activity(inputs=inputs(history, category=category), config=CONFIG)
    assert (result.state, result.since, result.reason) == (ActivityState.UNKNOWN, None, reason)


def test_not_evaluated_categories_are_unknown() -> None:
    result = assess_activity(
        inputs=inputs(cpu_series(FULL), category=Category.SYSTEM), config=CONFIG
    )
    assert result.state is ActivityState.UNKNOWN
    assert result.reason == "attività non valutata per questa categoria"


def test_unmeasured_last_cycle_does_not_cite_a_forgotten_tab() -> None:
    history = [replace(s, connections=frozenset({QUAD})) for s in cpu_series(FULL)]
    history[-1] = replace(history[-1], connections=None)
    inp = inputs(tuple(history), category=Category.DEV_SERVER, server_ports=frozenset({5173}))
    result = assess_activity(inputs=inp, config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert "scheda dimenticata" not in result.reason


def test_last_active_at_is_the_end_of_the_latest_active_step() -> None:
    from wimm.core.activity import last_active_at

    history = cpu_series(FULL, active_at={-1200, -1170, -300, -270})

    assert last_active_at(inputs=inputs(history), config=CONFIG) == at(-270)


def test_last_active_at_is_none_without_activity_in_the_window() -> None:
    from wimm.core.activity import last_active_at

    assert last_active_at(inputs=inputs(cpu_series(FULL, active_at=set())), config=CONFIG) is None
    # Positive pair: one active sample is enough to report it.
    assert last_active_at(inputs=inputs(cpu_series(FULL, active_at={-30})), config=CONFIG) == at(
        -30
    )
