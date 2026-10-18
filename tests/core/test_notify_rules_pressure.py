from datetime import timedelta

from wimm.core.notify_rules import evaluate_notifications
from wimm.core.notify_types import NotificationState

from .notify_helpers import GB, MB, NOW, make_group, make_snapshot, request, with_config


def test_ram_pressure_lists_top_three_groups_by_reclaimable() -> None:
    groups = (
        make_group("g_a", name="vite (frontend)", reclaimable=640 * MB),
        make_group("g_b", name="whitebox", reclaimable=1_100 * MB),
        make_group("g_c", name="jupyter", reclaimable=410 * MB),
        make_group("g_d", name="piccolo", reclaimable=50 * MB),
    )
    snapshot = make_snapshot(groups, ram_free_pct=7)

    result = evaluate_notifications(request=request(snapshot))

    pressure = [item for item in result.intents if item.id == "pressure-ram"]
    (intent,) = pressure
    assert intent.title == "Memoria quasi piena (7% libera)"
    assert (
        intent.body
        == "Puoi liberare subito: whitebox 1,1 GB, vite (frontend) 640 MB, jupyter 410 MB."
    )


def test_ram_pressure_boundary_is_strictly_below_critical_pct() -> None:
    at_limit = make_snapshot(ram_free_pct=10)
    below = make_snapshot(ram_free_pct=9)

    assert evaluate_notifications(request=request(at_limit)).intents == ()
    assert [i.id for i in evaluate_notifications(request=request(below)).intents] == [
        "pressure-ram"
    ]


def test_pressure_threshold_follows_configuration() -> None:
    snapshot = make_snapshot(ram_free_pct=12)
    config = with_config(pressure_critical_pct=5, pressure_warning_pct=15)
    wider = with_config(pressure_critical_pct=14, pressure_warning_pct=15)

    assert evaluate_notifications(request=request(snapshot, config=config)).intents == ()
    assert len(evaluate_notifications(request=request(snapshot, config=wider)).intents) == 1


def test_pressure_cooldown_one_hour_per_type() -> None:
    snapshot = make_snapshot(ram_free_pct=5)
    first = evaluate_notifications(request=request(snapshot))

    inside = evaluate_notifications(
        request=request(snapshot, state=first.state, now=NOW + timedelta(minutes=59))
    )
    after = evaluate_notifications(
        request=request(snapshot, state=first.state, now=NOW + timedelta(minutes=61))
    )

    assert len(first.intents) == 1
    assert inside.intents == ()
    assert [item.id for item in after.intents] == ["pressure-ram"]


def test_pressure_cooldown_ends_exactly_at_one_hour() -> None:
    snapshot = make_snapshot(ram_free_pct=5)
    first = evaluate_notifications(request=request(snapshot))

    at_hour = evaluate_notifications(
        request=request(snapshot, state=first.state, now=NOW + timedelta(hours=1))
    )

    assert [item.id for item in at_hour.intents] == ["pressure-ram"]


def test_disk_and_ram_cooldowns_are_independent() -> None:
    ram_only = evaluate_notifications(request=request(make_snapshot(ram_free_pct=5)))

    both = evaluate_notifications(
        request=request(make_snapshot(ram_free_pct=5, disk_free_pct=4), state=ram_only.state)
    )

    assert [item.id for item in both.intents] == ["pressure-disk"]
    assert both.intents[0].title == "Disco quasi pieno (4% libero)"


def test_disk_pressure_body_reports_reclaimable_disk() -> None:
    snapshot = make_snapshot(disk_free_pct=3, reclaimable_disk=3_200_000_000)

    (intent,) = evaluate_notifications(request=request(snapshot)).intents

    assert intent.body == "Puoi liberare subito 3,2 GB sul disco."


def test_pressure_excludes_ignored_groups_from_top_list() -> None:
    groups = (
        make_group("g_a", name="nascosto", reclaimable=2 * GB, ignored=True),
        make_group("g_b", name="visibile", reclaimable=1 * GB),
    )

    (intent, *_) = evaluate_notifications(
        request=request(make_snapshot(groups, ram_free_pct=5))
    ).intents

    assert intent.body == "Puoi liberare subito: visibile 1,0 GB."


def test_pressure_counts_toward_hourly_limit_for_idle() -> None:
    groups = tuple(make_group(f"g_{i}", reclaimable=(4 - i) * GB) for i in range(4))

    result = evaluate_notifications(request=request(make_snapshot(groups, ram_free_pct=5)))

    assert [item.id for item in result.intents] == [
        "pressure-ram",
        "idle-g_0",
        "idle-g_1",
        "idle-aggregate",
    ]
    assert len(result.state.sent_at) == 4


def test_global_silence_sends_nothing_and_notifies_when_it_ends() -> None:
    snapshot = make_snapshot((make_group(),), ram_free_pct=5)
    muted = NOW + timedelta(hours=1)

    during = evaluate_notifications(request=request(snapshot, muted_until=muted))
    ended = evaluate_notifications(
        request=request(snapshot, state=during.state, now=muted, muted_until=muted)
    )

    assert during.intents == ()
    assert sorted(item.id for item in ended.intents) == ["idle-g_1", "pressure-ram"]


def test_state_forgets_episodes_of_groups_that_disappeared() -> None:
    first = evaluate_notifications(request=request(make_snapshot((make_group(),))))

    after = evaluate_notifications(
        request=request(make_snapshot(()), state=first.state, now=NOW + timedelta(minutes=5))
    )

    assert first.state.episodes != frozenset()
    assert after.state.episodes == frozenset()
    assert NotificationState().episodes == frozenset()


def test_pressure_never_lists_a_protected_group_as_freeable() -> None:
    from wimm.model.enums import Category

    groups = (
        make_group("g_s", name="sessione", category=Category.SYSTEM, reclaimable=3 * GB),
        make_group("g_b", name="visibile", reclaimable=1 * GB),
    )

    (intent, *_) = evaluate_notifications(
        request=request(make_snapshot(groups, ram_free_pct=5))
    ).intents

    assert intent.body == "Puoi liberare subito: visibile 1,0 GB."


def test_a_clock_moved_back_does_not_silence_pressure_for_hours() -> None:
    later = NOW + timedelta(hours=3)
    state = NotificationState(frozenset(), {"ram": later}, (later,))

    result = evaluate_notifications(
        request=request(make_snapshot((), ram_free_pct=5), state=state, now=NOW)
    )

    assert [item.id for item in result.intents] == ["pressure-ram"]
