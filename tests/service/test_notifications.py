from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.core.notify_helpers import NOW, make_group, make_snapshot
from wimm.config import Config
from wimm.core.notify_rules import NotificationState
from wimm.model.enums import GroupId
from wimm.model.snapshot import Snapshot
from wimm.service.notifications import SNOOZE_DURATION, NotificationCoordinator
from wimm.service.notifier import Notifier
from wimm.service.state_store import PersistedState

GROUP = GroupId("g_1")


class FakeSource:
    def __init__(self, snapshot: Snapshot | None) -> None:
        self.current = snapshot
        self.notifications_muted_until: datetime | None = None
        self.handlers: list[Callable[..., None]] = []

    def snapshot(self) -> Snapshot | None:
        return self.current

    def config(self) -> Config:
        return Config()

    def connect(self, detailed_signal: str, handler: Callable[..., None]) -> int:
        assert detailed_signal == "snapshot-updated"
        self.handlers.append(handler)
        return len(self.handlers)

    def emit(self) -> None:
        for handler in self.handlers:
            handler(self)


class FakeSink:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    def send_notification(self, id: str | None, notification: Any) -> None:
        if self.fail:
            raise RuntimeError("bus gone")
        self.sent.append(str(id))

    def withdraw_notification(self, id: str) -> None:
        raise AssertionError("not expected")


class FakeSaver:
    def __init__(self) -> None:
        self.changes: list[Mapping[str, Any]] = []

    def update(self, *, changes: Mapping[str, Any]) -> None:
        self.changes.append(changes)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Rig:
    def __init__(self, *, state: PersistedState | None = None) -> None:
        self.source = FakeSource(make_snapshot((make_group(),)))
        self.sink = FakeSink()
        self.saver = FakeSaver()
        self.clock = Clock()
        self.coordinator = NotificationCoordinator(
            notifier=Notifier(sink=self.sink),
            saver=self.saver,
            state=state or PersistedState(),
            clock=self.clock,
        )
        self.coordinator.attach(source=self.source)

    def saved(self, section: str) -> Any:
        return [c[section] for c in self.saver.changes if section in c][-1]


def test_idle_group_is_notified_and_the_state_goes_to_the_saver() -> None:
    rig = Rig()
    rig.source.emit()
    assert rig.sink.sent == ["idle-g_1"]
    assert isinstance(rig.saved("notifications"), NotificationState)
    assert {group for group, _ in rig.saved("notifications").episodes} == {GROUP}


def test_an_unchanged_snapshot_does_not_send_again() -> None:
    rig = Rig()
    rig.source.emit()
    rig.source.emit()
    assert rig.sink.sent == ["idle-g_1"]


def test_an_episode_saved_before_a_restart_is_not_notified_again() -> None:
    first = Rig()
    first.source.emit()
    restarted = Rig(state=PersistedState(notifications=first.saved("notifications")))
    restarted.source.emit()
    assert restarted.sink.sent == []


def test_global_mute_blocks_the_notification() -> None:
    rig = Rig()
    rig.source.notifications_muted_until = NOW + timedelta(hours=1)
    rig.source.emit()
    assert rig.sink.sent == []


def test_no_snapshot_yet_sends_nothing() -> None:
    rig = Rig()
    rig.source.current = None
    rig.source.emit()
    assert rig.sink.sent == []


def test_a_failing_sink_is_contained_and_the_next_cycle_retries() -> None:
    rig = Rig()
    rig.sink.fail = True
    rig.source.emit()
    assert rig.sink.sent == []
    assert not rig.saver.changes
    rig.sink.fail = False
    rig.source.emit()
    assert rig.sink.sent == ["idle-g_1"]


def test_snooze_group_silences_it_for_24_hours_and_persists() -> None:
    rig = Rig()
    rig.coordinator.snooze_group(group_id=GROUP)
    assert rig.saved("snoozes") == {GROUP: NOW + SNOOZE_DURATION}
    assert timedelta(hours=24) == SNOOZE_DURATION
    rig.source.emit()
    assert rig.sink.sent == []
    rig.clock.now = NOW + SNOOZE_DURATION + timedelta(seconds=1)
    rig.source.current = make_snapshot((make_group(),))
    rig.source.emit()
    assert rig.sink.sent == ["idle-g_1"]


def test_a_snooze_loaded_at_startup_is_honoured_and_expired_ones_are_dropped() -> None:
    state = PersistedState(snoozes={GROUP: NOW + timedelta(hours=1)})
    rig = Rig(state=state)
    rig.source.emit()
    assert rig.sink.sent == []
    rig.coordinator.snooze_group(group_id=GroupId("other"))
    rig.clock.now = NOW + timedelta(hours=2)
    rig.coordinator.snooze_group(group_id=GroupId("third"))
    assert set(rig.saved("snoozes")) == {GroupId("other"), GroupId("third")}


def test_snooze_of_an_empty_target_is_ignored() -> None:
    rig = Rig()
    rig.coordinator.snooze_group(group_id=GroupId(""))
    assert not rig.saver.changes


def test_snooze_does_not_touch_other_groups() -> None:
    rig = Rig()
    other = replace(make_group("g_2", name="vite"), snoozed_until=None)
    rig.source.current = make_snapshot((make_group(), other))
    rig.coordinator.snooze_group(group_id=GROUP)
    rig.source.emit()
    assert rig.sink.sent == ["idle-g_2"]


@pytest.mark.parametrize("hours", [0, 3])
def test_snoozed_until_in_the_past_does_not_silence(hours: int) -> None:
    rig = Rig(state=PersistedState(snoozes={GROUP: NOW - timedelta(hours=hours)}))
    rig.source.emit()
    assert rig.sink.sent == ["idle-g_1"]
