import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.core.notify_helpers import make_group, make_snapshot
from tests.service.service_helpers import FakeSampler, FixedClock, spin_until
from wimm.config import Config
from wimm.core.assemble import UserState
from wimm.model.enums import GroupId
from wimm.model.snapshot import Group, Snapshot
from wimm.service.app_service import AppService
from wimm.service.notifications import NotificationCoordinator
from wimm.service.notifier import Notifier
from wimm.service.state_store import PersistedState

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
GROUP = GroupId("g_1")


class RecordingSampler(FakeSampler):
    """Applies the user state it received the way the real sampler does."""

    def __init__(self) -> None:
        super().__init__()
        self.users: list[tuple[UserState, int]] = []
        self.proceed.set()

    def apply_user_state(self, *, user: UserState) -> None:
        self.users.append((user, threading.get_ident()))

    def run_cycle(self) -> Snapshot:
        super().run_cycle()
        user = self.users[-1][0] if self.users else UserState()
        group = replace(
            make_group(),
            ignored=GROUP in user.ignored,
            snoozed_until=user.snoozed_until.get(GROUP),
        )
        return make_snapshot((group,))


class Sink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_notification(self, id: str | None, notification: Any) -> None:
        self.sent.append(str(id))

    def withdraw_notification(self, id: str) -> None:
        raise AssertionError("not expected")


def make_service(
    *, state: PersistedState | None = None
) -> tuple[AppService, RecordingSampler, FixedClock]:
    sampler = RecordingSampler()
    clock = FixedClock(NOW)
    service = AppService(sampler=sampler, config=Config(), clock=clock)
    service.restore_user_state(state=state or PersistedState())
    return service, sampler, clock


def current_group(service: AppService) -> Group:
    snapshot = service.snapshot()
    assert snapshot is not None
    return snapshot.groups[0]


def test_snooze_reaches_the_sampler_on_the_worker_and_shows_in_the_next_snapshot() -> None:
    service, sampler, _ = make_service()
    try:
        service.start()
        spin_until(predicate=lambda: service.snapshot() is not None)
        service.snooze(group_id=GROUP, duration_s=3600)
        spin_until(predicate=lambda: current_group(service).snoozed_until is not None)
        assert current_group(service).snoozed_until == NOW + timedelta(hours=1)
        assert sampler.users[-1][1] == sampler.cycle_threads[0] != threading.get_ident()
    finally:
        service.stop()


def test_set_ignored_shows_in_the_next_snapshot_and_false_restores() -> None:
    service, _, _ = make_service()
    try:
        service.start()
        spin_until(predicate=lambda: service.snapshot() is not None)
        service.set_ignored(group_id=GROUP, ignored=True)
        spin_until(predicate=lambda: current_group(service).ignored)
        service.set_ignored(group_id=GROUP, ignored=False)
        spin_until(predicate=lambda: not current_group(service).ignored)
    finally:
        service.stop()


def test_state_restored_at_startup_reaches_the_first_snapshot() -> None:
    state = PersistedState(ignored=frozenset({GROUP}), snoozes={GROUP: NOW + timedelta(hours=1)})
    service, _, _ = make_service(state=state)
    try:
        service.start()
        spin_until(predicate=lambda: service.snapshot() is not None)
        group = current_group(service)
        assert group.ignored and group.snoozed_until == NOW + timedelta(hours=1)
    finally:
        service.stop()


def notifications_sent(*, mute: bool) -> list[str]:
    service, _, clock = make_service()
    sink = Sink()
    coordinator = NotificationCoordinator(
        notifier=Notifier(sink=sink), saver=None, state=PersistedState(), clock=clock
    )
    coordinator.attach(source=service)
    try:
        if mute:
            service.snooze_all(duration_s=3600)
        service.start()
        spin_until(predicate=lambda: service.snapshot() is not None)
    finally:
        service.stop()
    return sink.sent


def test_snooze_all_silences_every_notification_and_without_it_they_are_sent() -> None:
    assert notifications_sent(mute=False) == ["idle-g_1"]
    assert notifications_sent(mute=True) == []


def test_snooze_all_requests_a_new_cycle_and_expires() -> None:
    service, sampler, clock = make_service()
    try:
        service.start()
        spin_until(predicate=lambda: service.snapshot() is not None)
        service.snooze_all(duration_s=60)
        spin_until(predicate=lambda: sampler.calls == 2)
        assert service.notifications_muted_until == NOW + timedelta(seconds=60)
        clock.now = NOW + timedelta(seconds=60)
        assert service.notifications_muted_until is None
    finally:
        service.stop()


def test_a_snooze_during_a_running_cycle_samples_again_when_it_ends() -> None:
    # The cycle in flight was taken before the snooze: one more must follow at once,
    # not one sample interval later.
    service, sampler, _ = make_service()
    sampler.proceed.clear()
    try:
        service.start()
        spin_until(predicate=lambda: sampler.calls == 1)  # first cycle is running
        service.snooze(group_id=GROUP, duration_s=3600)
        sampler.proceed.set()
        spin_until(predicate=lambda: sampler.calls >= 2)
        spin_until(predicate=lambda: current_group(service).snoozed_until is not None)
    finally:
        service.stop()


def test_restoring_the_user_state_after_attaching_the_saver_is_refused(tmp_path: Path) -> None:
    import pytest

    from wimm.paths import UserPaths
    from wimm.service.errors import InvalidRequest
    from wimm.service.state_store import StateSaver

    service, _, _ = make_service()
    paths = UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )
    saver = StateSaver(paths=paths, state=PersistedState(), last_active=dict)
    service.attach_state_saver(saver=saver)

    with pytest.raises(InvalidRequest):
        service.restore_user_state(state=PersistedState())
