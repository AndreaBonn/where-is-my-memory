from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

import pytest

from tests.core.assemble_helpers import draft
from tests.core.helpers import FIREFOX, process
from tests.service.sampler_helpers import NOW, make_sampler
from wimm.collectors import CollectorResult
from wimm.collectors.foreground import (
    DISABLED_STATE,
    UNAVAILABLE_STATE,
    ForegroundReader,
    ForegroundState,
    ForegroundStatus,
)
from wimm.collectors.foreground_wayland import WaylandForegroundReader
from wimm.config import Config
from wimm.model.enums import ActivityState, Category
from wimm.model.snapshot import Group
from wimm.service.sampler import Sampler
from wimm.service.sampler_collectors import ForegroundSource
from wimm.service.sampler_steps import foreground_group_pids

STEP_S = 30
WINDOW_S = 300
FIREFOX_PID, HELPER_PID, NODE_PID = 10, 11, 20
CONFIG = Config(activity_window_s=WINDOW_S, sample_interval_s=STEP_S)
UNMEASURABLE_BROWSER = "attività non misurabile per i browser"


def focused(pid: int) -> ForegroundState:
    return ForegroundState(status=ForegroundStatus.ACTIVE, pid=pid)


class FakeForeground:
    """Reader factory whose current answer the test sets; honours ``enabled``."""

    def __init__(self, state: ForegroundState) -> None:
        self.state = state
        self.enabled_requests: list[bool] = []
        self._enabled = False

    def __call__(self, *, enabled: bool) -> "FakeForeground":
        self.enabled_requests.append(enabled)
        self._enabled = enabled
        return self

    def read(self) -> ForegroundState:
        return self.state if self._enabled else DISABLED_STATE


def _at(*, seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


def build_sampler(
    *, tmp_path: Path, foreground: Callable[..., ForegroundSource], config: Config = CONFIG
) -> Sampler:
    base = make_sampler(tmp_path=tmp_path)
    procs = (
        process(pid=FIREFOX_PID, name="firefox", create_time=1, cgroup=FIREFOX, cpu_time_s=0),
        process(pid=HELPER_PID, ppid=FIREFOX_PID, name="firefox", create_time=2, cgroup=FIREFOX),
        process(pid=NODE_PID, name="node", cmdline=("node",), create_time=3, cpu_time_s=0),
    )
    collectors = replace(
        base.collectors, processes=lambda: CollectorResult(data=procs), foreground=foreground
    )
    return Sampler(
        collectors=collectors, environment=base.environment, config=config, clock=lambda: NOW
    )


def browser(sampler: Sampler, *, second: int) -> Group:
    sampler.clock = partial(_at, seconds=second)
    snapshot = sampler.run_cycle()
    return next(g for g in snapshot.groups if g.category is Category.BROWSER)


def run_until(sampler: Sampler, *, start: int, end: int) -> Group:
    group = None
    for second in range(start, end + STEP_S, STEP_S):
        group = browser(sampler, second=second)
    assert group is not None
    return group


def test_app_never_in_foreground_for_the_window_is_idle(tmp_path: Path) -> None:
    sampler = build_sampler(tmp_path=tmp_path, foreground=FakeForeground(focused(NODE_PID)))
    group = run_until(sampler, start=0, end=WINDOW_S + STEP_S)
    assert group.activity.state is ActivityState.IDLE
    assert all(
        "mai in primo piano negli ultimi 5 minuti" in m.activity.reason for m in group.members
    )


def test_app_in_foreground_once_is_active_then_idle_after_the_window(tmp_path: Path) -> None:
    fake = FakeForeground(focused(NODE_PID))
    sampler = build_sampler(tmp_path=tmp_path, foreground=fake)
    run_until(sampler, start=0, end=60)
    fake.state = focused(HELPER_PID)  # a child window: the whole group counts
    browser(sampler, second=90)
    fake.state = focused(NODE_PID)
    active = run_until(sampler, start=120, end=WINDOW_S + 60)
    assert active.activity.state is ActivityState.ACTIVE
    assert active.activity.since == _at(seconds=90)
    assert {m.activity.state for m in active.members} == {ActivityState.ACTIVE}
    idle = run_until(sampler, start=WINDOW_S + 90, end=WINDOW_S + 150)
    assert idle.activity.state is ActivityState.IDLE
    assert idle.activity.since == _at(seconds=90)


def test_disabling_foreground_tracking_makes_the_group_unknown(tmp_path: Path) -> None:
    fake = FakeForeground(focused(NODE_PID))
    sampler = build_sampler(tmp_path=tmp_path, foreground=fake)
    before = run_until(sampler, start=0, end=WINDOW_S + STEP_S)
    assert before.activity.state is ActivityState.IDLE
    sampler.apply_config(config=replace(CONFIG, foreground_tracking=False))
    after = browser(sampler, second=WINDOW_S + 2 * STEP_S)
    assert after.activity.state is ActivityState.UNKNOWN
    assert {m.activity.reason for m in after.members} == {UNMEASURABLE_BROWSER}
    assert fake.enabled_requests == [True, False]


def test_reenabling_foreground_tracking_resumes_measuring(tmp_path: Path) -> None:
    fake = FakeForeground(focused(FIREFOX_PID))
    sampler = build_sampler(tmp_path=tmp_path, foreground=fake)
    sampler.apply_config(config=replace(CONFIG, foreground_tracking=False))
    assert browser(sampler, second=0).activity.state is ActivityState.UNKNOWN
    sampler.apply_config(config=CONFIG)
    assert browser(sampler, second=STEP_S).activity.state is ActivityState.ACTIVE


@pytest.mark.parametrize("state", [DISABLED_STATE, UNAVAILABLE_STATE])
def test_unavailable_foreground_never_makes_the_group_idle(
    tmp_path: Path, state: ForegroundState
) -> None:
    sampler = build_sampler(tmp_path=tmp_path, foreground=FakeForeground(state))
    group = run_until(sampler, start=0, end=2 * WINDOW_S)
    assert group.activity.state is ActivityState.UNKNOWN
    assert {m.activity.reason for m in group.members} == {UNMEASURABLE_BROWSER}


def test_wayland_session_leaves_the_state_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The production path: from_environment picks the Wayland reader from the environment.
    # The session bus points at a socket nobody listens on, so the focus name has no owner.
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path / 'no-bus'}")
    reader = ForegroundReader.from_environment(enabled=True)
    assert isinstance(reader, WaylandForegroundReader)
    assert reader.read() is UNAVAILABLE_STATE

    sampler = build_sampler(tmp_path=tmp_path, foreground=ForegroundReader.from_environment)
    group = run_until(sampler, start=0, end=2 * WINDOW_S)
    assert group.activity.state is ActivityState.UNKNOWN
    assert {m.activity.reason for m in group.members} == {UNMEASURABLE_BROWSER}


def test_foreground_flag_is_recorded_per_process_each_cycle(tmp_path: Path) -> None:
    fake = FakeForeground(focused(HELPER_PID))
    sampler = build_sampler(tmp_path=tmp_path, foreground=fake)
    browser(sampler, second=0)
    flags = {
        pid: sampler.history.history_for(key=(pid, float(ct)))[-1].foreground
        for pid, ct in ((FIREFOX_PID, 1), (HELPER_PID, 2), (NODE_PID, 3))
    }
    assert flags == {FIREFOX_PID: True, HELPER_PID: True, NODE_PID: False}
    fake.state = UNAVAILABLE_STATE
    browser(sampler, second=STEP_S)
    assert sampler.history.history_for(key=(NODE_PID, 3.0))[-1].foreground is None


GROUPS = (draft("g_f", pids=[10, 11]), draft("g_n", pids=[20]))
PROCESSES = {
    10: process(pid=10, ppid=1),
    11: process(pid=11, ppid=10),
    12: process(pid=12, ppid=11),
    20: process(pid=20, ppid=1),
}


@pytest.mark.parametrize(
    ("pid", "expected"),
    [
        (11, frozenset({10, 11})),
        (20, frozenset({20})),
        (12, frozenset({10, 11})),  # grandchild window owner: walks up to the member
    ],
)
def test_foreground_group_pids_resolves_the_group_of_the_window_owner(
    pid: int, expected: frozenset[int]
) -> None:
    result = foreground_group_pids(state=focused(pid), drafts=GROUPS, processes=PROCESSES)
    assert result == expected


@pytest.mark.parametrize("state", [DISABLED_STATE, UNAVAILABLE_STATE])
def test_foreground_group_pids_is_none_without_a_reading(state: ForegroundState) -> None:
    assert foreground_group_pids(state=state, drafts=GROUPS, processes=PROCESSES) is None


def test_foreground_group_pids_is_none_for_a_window_owner_it_cannot_see() -> None:
    # A Flatpak window reports a pid of its own namespace: unknown, not "in background".
    assert foreground_group_pids(state=focused(99), drafts=GROUPS, processes=PROCESSES) is None
    known_untracked = {**PROCESSES, 99: process(pid=99, ppid=1)}
    assert (
        foreground_group_pids(state=focused(99), drafts=GROUPS, processes=known_untracked)
        == frozenset()
    )


def test_foreground_group_pids_survives_a_parent_cycle() -> None:
    loop = {5: process(pid=5, ppid=6), 6: process(pid=6, ppid=5)}
    assert foreground_group_pids(state=focused(5), drafts=GROUPS, processes=loop) == frozenset()
