from datetime import timedelta

import pytest

from wimm.core.activity import (
    EntitySample,
    GroupMember,
    assess_activity,
    assess_group_activity,
    is_measurable,
    last_active_at,
)
from wimm.model.enums import ActivityState, Category

from .activity_helpers import CONFIG, FULL, INTERVAL, NOW, WINDOW, at, inputs, sample

FOREGROUND_CATEGORIES = [Category.BROWSER, Category.DESKTOP_APP, Category.TERMINAL]
UNAVAILABLE = "attività non misurabile"


def fg_series(
    offsets: list[int], *, seen_at: tuple[int, ...] = (), value: bool | None = False
) -> tuple[EntitySample, ...]:
    """Samples at ``offsets``: True at ``seen_at``, ``value`` elsewhere."""
    return tuple(sample(o, foreground=True if o in seen_at else value) for o in offsets)


@pytest.mark.parametrize("category", FOREGROUND_CATEGORIES)
def test_any_foreground_sample_in_the_window_is_active(category: Category) -> None:
    history = fg_series(FULL, seen_at=(-600,))
    result = assess_activity(inputs=inputs(history, category=category), config=CONFIG)
    assert result.state is ActivityState.ACTIVE
    assert result.since == at(-600)


def test_active_since_is_the_latest_foreground_sample() -> None:
    history = fg_series(FULL, seen_at=(-900, -870, -300))
    result = assess_activity(inputs=inputs(history, category=Category.BROWSER), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-300))
    assert result.reason == "in primo piano 5 minuti fa"


@pytest.mark.parametrize("category", FOREGROUND_CATEGORIES)
def test_full_window_without_foreground_is_idle_since_monitor_start(category: Category) -> None:
    result = assess_activity(inputs=inputs(fg_series(FULL), category=category), config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert result.since == NOW - timedelta(hours=3)
    assert "mai in primo piano negli ultimi 30 minuti" in result.reason
    assert "da quando il monitor è partito" in result.reason


def test_idle_counts_from_the_persisted_last_active_instant() -> None:
    persisted = NOW - timedelta(hours=1)
    result = assess_activity(
        inputs=inputs(
            fg_series(FULL), category=Category.DESKTOP_APP, persisted_last_active=persisted
        ),
        config=CONFIG,
    )
    assert (result.state, result.since) == (ActivityState.IDLE, persisted)
    assert "monitor" not in result.reason


def test_foreground_before_the_window_does_not_count() -> None:
    offsets = [-WINDOW - 2 * INTERVAL, *FULL]
    history = fg_series(offsets, seen_at=(offsets[0],))
    result = assess_activity(inputs=inputs(history, category=Category.BROWSER), config=CONFIG)
    assert result.state is ActivityState.IDLE


def test_cpu_activity_is_not_foreground_activity() -> None:
    busy = tuple(sample(o, cpu_time_s=30.0 * i, foreground=False) for i, o in enumerate(FULL))
    result = assess_activity(inputs=inputs(busy, category=Category.BROWSER), config=CONFIG)
    assert result.state is ActivityState.IDLE


def test_short_history_without_foreground_is_still_observing() -> None:
    history = fg_series([-120, -90, -60, -30, 0])
    result = assess_activity(inputs=inputs(history, category=Category.TERMINAL), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.UNKNOWN, None)
    assert result.reason.startswith("in osservazione da")


def test_short_history_with_foreground_is_active() -> None:
    history = fg_series([-120, -90, -60, -30, 0], seen_at=(-90,))
    result = assess_activity(inputs=inputs(history, category=Category.TERMINAL), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-90))


def test_unavailable_foreground_is_unknown_never_idle() -> None:
    history = fg_series(FULL, value=None)
    result = assess_activity(inputs=inputs(history, category=Category.BROWSER), config=CONFIG)
    assert (result.state, result.since) == (ActivityState.UNKNOWN, None)
    assert result.reason == "attività non misurabile per i browser"


def test_unavailable_latest_cycle_keeps_an_earlier_foreground_sample_active() -> None:
    # One failed read (alt-tab, xprop timeout) must not hide a foreground sample in the window.
    history = (*fg_series(FULL[:-1], seen_at=(-600,)), sample(0, foreground=None))
    result = assess_activity(inputs=inputs(history, category=Category.TERMINAL), config=CONFIG)
    assert result.state is ActivityState.ACTIVE


def test_unavailable_latest_cycle_without_foreground_samples_is_unknown() -> None:
    history = (*fg_series(FULL[:-1], seen_at=()), sample(0, foreground=None))
    result = assess_activity(inputs=inputs(history, category=Category.TERMINAL), config=CONFIG)
    assert result.state is ActivityState.UNKNOWN
    assert result.reason == "attività non misurabile per i terminali"


def test_a_gap_in_the_window_blocks_idle_but_not_active() -> None:
    gap = tuple(sample(o, foreground=None if o == -900 else False) for o in FULL)
    blocked = assess_activity(inputs=inputs(gap, category=Category.BROWSER), config=CONFIG)
    assert blocked.state is ActivityState.UNKNOWN
    seen = tuple(
        sample(o, foreground=True if o == -300 else gap[i].foreground) for i, o in enumerate(FULL)
    )
    result = assess_activity(inputs=inputs(seen, category=Category.BROWSER), config=CONFIG)
    assert result.state is ActivityState.ACTIVE


def test_other_categories_ignore_foreground_samples() -> None:
    history = tuple(sample(o, cpu_time_s=0.0, foreground=True) for o in FULL)
    result = assess_activity(inputs=inputs(history, category=Category.DEV_PROCESS), config=CONFIG)
    assert result.state is ActivityState.IDLE
    assert "mai in primo piano" not in result.reason


def test_last_active_at_is_the_latest_foreground_sample_or_none() -> None:
    seen = inputs(fg_series(FULL, seen_at=(-600, -300)), category=Category.BROWSER)
    assert last_active_at(inputs=seen, config=CONFIG) == at(-300)
    never = inputs(fg_series(FULL), category=Category.BROWSER)
    assert last_active_at(inputs=never, config=CONFIG) is None


def test_foreground_categories_count_as_measurable_for_groups() -> None:
    assert all(is_measurable(category=c) for c in FOREGROUND_CATEGORIES)
    assert not is_measurable(category=Category.SYSTEM)


def _member(*, seen_at: tuple[int, ...] = (), value: bool | None = False) -> GroupMember:
    history = fg_series(FULL, seen_at=seen_at, value=value)
    assessment = assess_activity(inputs=inputs(history, category=Category.BROWSER), config=CONFIG)
    return GroupMember(assessment=assessment, measurable=True)


def test_group_is_active_when_one_process_was_in_foreground() -> None:
    group = assess_group_activity(members=[_member(), _member(seen_at=(-600,)), _member()])
    assert (group.state, group.since) == (ActivityState.ACTIVE, at(-600))


def test_group_is_idle_when_no_process_was_in_foreground() -> None:
    group = assess_group_activity(members=[_member(), _member(), _member()])
    assert group.state is ActivityState.IDLE


def test_group_stays_unknown_when_foreground_is_unavailable() -> None:
    group = assess_group_activity(members=[_member(value=None), _member(value=None)])
    assert group.state is ActivityState.UNKNOWN


def test_foreground_sample_exactly_at_the_window_start_is_active() -> None:
    history = fg_series(FULL, seen_at=(-WINDOW,))

    result = assess_activity(inputs=inputs(history, category=Category.BROWSER), config=CONFIG)

    assert (result.state, result.since) == (ActivityState.ACTIVE, at(-WINDOW))


def test_foreground_sample_one_second_before_the_window_start_does_not_count() -> None:
    offsets = [-WINDOW - 1, *FULL]
    history = fg_series(offsets, seen_at=(-WINDOW - 1,))

    result = assess_activity(inputs=inputs(history, category=Category.BROWSER), config=CONFIG)

    assert result.state is ActivityState.IDLE


def test_foreground_category_with_empty_history_is_observing() -> None:
    result = assess_activity(inputs=inputs((), category=Category.BROWSER), config=CONFIG)

    assert (result.state, result.since) == (ActivityState.UNKNOWN, None)
    assert result.reason == "in osservazione da meno di 1 minuto"


def test_foreground_empty_history_with_a_recent_persisted_instant_is_still_observing() -> None:
    recent = NOW - timedelta(minutes=10)

    result = assess_activity(
        inputs=inputs((), category=Category.BROWSER, persisted_last_active=recent), config=CONFIG
    )

    assert (result.state, result.since) == (ActivityState.UNKNOWN, None)


def test_foreground_empty_history_with_an_old_persisted_instant_is_idle() -> None:
    persisted = NOW - timedelta(hours=1)

    result = assess_activity(
        inputs=inputs((), category=Category.BROWSER, persisted_last_active=persisted),
        config=CONFIG,
    )

    assert (result.state, result.since) == (ActivityState.IDLE, persisted)
    assert result.reason.startswith("inattivo da 60 minuti")
