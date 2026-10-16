import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from time import monotonic

from gi.repository import GLib

from tests.core.assemble_helpers import build_input
from wimm.core.assemble import assemble_snapshot
from wimm.model.snapshot import Snapshot

TIMEOUT_S = 5


def spin_until(predicate: Callable[[], bool]) -> None:
    context = GLib.MainContext.default()
    deadline = monotonic() + TIMEOUT_S
    while not predicate() and monotonic() < deadline:
        context.iteration(may_block=False)
    assert predicate()


def spin_for(seconds: float) -> None:
    context = GLib.MainContext.default()
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        context.iteration(may_block=False)


class FakeSampler:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.proceed = threading.Event()
        self.calls = 0
        self.fail = False
        self.current: Snapshot | None = None

    def run_cycle(self) -> Snapshot:
        self.calls += 1
        self.entered.set()
        # Captured on entry: what a real sample reads is fixed when the cycle starts.
        result = self.current or assemble_snapshot(inputs=build_input([]))
        assert self.proceed.wait(timeout=TIMEOUT_S)
        if self.fail:
            raise RuntimeError("sample failed")
        return result


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def with_free_space(*, snapshot: Snapshot, available: int, free: int) -> Snapshot:
    """Copy of `snapshot` with the two counters the reclaim delta reads."""
    memory = replace(snapshot.memory, total=1000, available=available, used=1000 - available)
    disk = replace(snapshot.disk, total=1000, free=free, used=1000 - free)
    return replace(snapshot, memory=memory, disk=disk)
