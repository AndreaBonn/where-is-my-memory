from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from wimm.service.user_state import UserStateKeeper

from tests.service.service_helpers import FixedClock
from wimm.model.enums import GroupId
from wimm.service.state_store import PersistedState

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
GROUP = GroupId("g_1")
OTHER = GroupId("g_2")


class FakeSaver:
    def __init__(self) -> None:
        self.changes: list[Mapping[str, Any]] = []

    def update(self, *, changes: Mapping[str, Any]) -> None:
        self.changes.append(changes)


def make_keeper(
    *, state: PersistedState | None = None
) -> tuple[UserStateKeeper, FixedClock, FakeSaver]:
    clock = FixedClock(NOW)
    saver = FakeSaver()
    keeper = UserStateKeeper(clock=clock, state=state or PersistedState())
    keeper.attach_saver(saver=saver)
    return keeper, clock, saver


def test_snooze_is_visible_in_the_user_state_until_it_expires() -> None:
    keeper, clock, _ = make_keeper()
    keeper.snooze(group_id=GROUP, duration_s=3600)
    assert dict(keeper.user_state().snoozed_until) == {GROUP: NOW + timedelta(hours=1)}
    clock.now = NOW + timedelta(hours=1)
    assert dict(keeper.user_state().snoozed_until) == {}


def test_snooze_is_persisted_without_the_expired_ones() -> None:
    keeper, clock, saver = make_keeper(
        state=PersistedState(snoozes={OTHER: NOW + timedelta(minutes=2)})
    )
    keeper.snooze(group_id=GROUP, duration_s=60)
    assert saver.changes[-1]["snoozes"] == {
        GROUP: NOW + timedelta(seconds=60),
        OTHER: NOW + timedelta(minutes=2),
    }
    clock.now = NOW + timedelta(minutes=5)
    keeper.snooze(group_id=GROUP, duration_s=60)
    assert dict(saver.changes[-1]["snoozes"]) == {GROUP: clock.now + timedelta(seconds=60)}


def test_set_ignored_adds_persists_and_false_restores() -> None:
    keeper, _, saver = make_keeper()
    keeper.set_ignored(group_id=GROUP, ignored=True)
    assert keeper.user_state().ignored == frozenset({GROUP})
    assert saver.changes[-1]["ignored"] == frozenset({GROUP})
    keeper.set_ignored(group_id=GROUP, ignored=False)
    assert keeper.user_state().ignored == frozenset()
    assert saver.changes[-1]["ignored"] == frozenset()


def test_a_restart_keeps_ignored_and_live_snoozes_and_drops_expired_ones() -> None:
    state = PersistedState(
        ignored=frozenset({GROUP}),
        snoozes={GROUP: NOW + timedelta(hours=2), OTHER: NOW - timedelta(seconds=1)},
    )
    keeper, _, _ = make_keeper(state=state)
    user = keeper.user_state()
    assert user.ignored == frozenset({GROUP})
    assert dict(user.snoozed_until) == {GROUP: NOW + timedelta(hours=2)}


def test_snooze_all_sets_an_expiry_that_lapses_with_the_clock() -> None:
    keeper, clock, saver = make_keeper()
    assert keeper.muted_until is None
    keeper.snooze_all(duration_s=3600)
    assert keeper.muted_until == NOW + timedelta(hours=1)
    clock.now = NOW + timedelta(minutes=59)
    assert keeper.muted_until == NOW + timedelta(hours=1)
    clock.now = NOW + timedelta(hours=1)
    assert keeper.muted_until is None
    assert saver.changes == []


@pytest.mark.parametrize("duration_s", [0, -1])
def test_non_positive_durations_are_rejected(duration_s: float) -> None:
    keeper, _, saver = make_keeper()
    with pytest.raises(ValueError, match="duration_s"):
        keeper.snooze(group_id=GROUP, duration_s=duration_s)
    with pytest.raises(ValueError, match="duration_s"):
        keeper.snooze_all(duration_s=duration_s)
    assert saver.changes == []


def test_an_empty_group_id_is_rejected() -> None:
    keeper, _, _ = make_keeper()
    with pytest.raises(ValueError, match="group_id"):
        keeper.snooze(group_id=GroupId(""), duration_s=60)
    with pytest.raises(ValueError, match="group_id"):
        keeper.set_ignored(group_id=GroupId(""), ignored=True)


def test_without_a_saver_changes_still_apply() -> None:
    keeper = UserStateKeeper(clock=FixedClock(NOW), state=PersistedState())
    keeper.set_ignored(group_id=GROUP, ignored=True)
    assert keeper.user_state().ignored == frozenset({GROUP})
