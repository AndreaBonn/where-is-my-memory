import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from gi.repository import GLib

from tests.core.assemble_helpers import build_input
from wimm.config import Config
from wimm.core.assemble import assemble_snapshot
from wimm.model.snapshot import Snapshot
from wimm.service.app_service import AppService

TIMEOUT_S = 5


def spin_until(predicate: Callable[[], bool]) -> None:
    context = GLib.MainContext.default()
    deadline = monotonic() + TIMEOUT_S
    while not predicate() and monotonic() < deadline:
        context.iteration(may_block=False)
    assert predicate()


class FakeSampler:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.proceed = threading.Event()
        self.calls = 0
        self.fail = False

    def run_cycle(self) -> Snapshot:
        self.calls += 1
        self.entered.set()
        assert self.proceed.wait(timeout=TIMEOUT_S)
        if self.fail:
            raise RuntimeError("sample failed")
        return assemble_snapshot(inputs=build_input([]))


def test_service_emits_on_main_thread_and_never_overlaps() -> None:
    sampler = FakeSampler()
    service = AppService(sampler=sampler, config=Config())
    threads: list[int] = []
    service.connect("snapshot-updated", lambda *_: threads.append(threading.get_ident()))
    try:
        service.start()
        assert sampler.entered.wait(timeout=TIMEOUT_S)
        for _ in range(5):
            service.request_cycle()
        assert sampler.calls == 1
        assert service.snapshot() is None
        sampler.proceed.set()
        spin_until(predicate=lambda: bool(threads))
        assert threads == [threading.get_ident()]
        assert service.snapshot() == assemble_snapshot(inputs=build_input([]))
        assert service.config() == Config()
    finally:
        sampler.proceed.set()
        service.stop()


def test_service_failure_recovers_and_stop_discards_completion() -> None:
    sampler = FakeSampler()
    sampler.proceed.set()
    sampler.fail = True
    service = AppService(sampler=sampler, config=Config())
    try:
        service.start()
        spin_until(predicate=lambda: service.consecutive_failures == 1)
        assert service.snapshot() is None
        sampler.fail = False
        service.request_cycle()
        spin_until(predicate=lambda: service.snapshot() is not None)
        assert service.consecutive_failures == 0
        service.stop()
        service.request_cycle()
        assert sampler.calls == 2
    finally:
        service.stop()


def test_stop_discards_worker_result_already_queued_for_main_loop() -> None:
    sampler = FakeSampler()
    service = AppService(sampler=sampler, config=Config())
    emissions: list[bool] = []
    service.connect("snapshot-updated", lambda *_: emissions.append(True))
    service.start()
    assert sampler.entered.wait(timeout=TIMEOUT_S)
    sampler.proceed.set()
    service.stop()
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(may_block=False)
    assert service.snapshot() is None
    assert emissions == []
    successful = AppService(sampler=sampler, config=Config())
    try:
        successful.connect("snapshot-updated", lambda *_: emissions.append(True))
        successful.start()
        spin_until(predicate=lambda: bool(emissions))
        assert successful.snapshot() == assemble_snapshot(inputs=build_input([]))
    finally:
        successful.stop()


def test_failed_cycle_emits_cycle_failed_with_updated_counter() -> None:
    sampler = FakeSampler()
    sampler.proceed.set()
    sampler.fail = True
    service = AppService(sampler=sampler, config=Config())
    seen: list[int] = []
    updates: list[bool] = []
    service.connect("cycle-failed", lambda s: seen.append(s.consecutive_failures))
    service.connect("snapshot-updated", lambda *_: updates.append(True))
    try:
        service.start()
        spin_until(predicate=lambda: bool(seen))
        assert seen == [1]
        assert updates == []
        sampler.fail = False
        service.request_cycle()
        spin_until(predicate=lambda: bool(updates))
        assert seen == [1]
    finally:
        service.stop()


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_mute_notifications_sets_expiry_that_lapses_with_the_clock() -> None:
    start = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    clock = FixedClock(start)
    service = AppService(sampler=FakeSampler(), config=Config(), clock=clock)
    try:
        assert service.notifications_muted_until is None
        service.mute_notifications(duration_s=3600)
        assert service.notifications_muted_until == start + timedelta(hours=1)
        clock.now = start + timedelta(minutes=59)
        assert service.notifications_muted_until == start + timedelta(hours=1)
        clock.now = start + timedelta(hours=1)
        assert service.notifications_muted_until is None
    finally:
        service.stop()


def test_mute_notifications_rejects_non_positive_duration() -> None:
    service = AppService(sampler=FakeSampler(), config=Config())
    try:
        with pytest.raises(ValueError, match="duration_s"):
            service.mute_notifications(duration_s=0)
        service.mute_notifications(duration_s=1)
        assert service.notifications_muted_until is not None
    finally:
        service.stop()
