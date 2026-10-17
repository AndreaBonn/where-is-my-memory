import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from wimm.collectors.foreground import (
    ForegroundReader,
    ForegroundState,
    ForegroundStatus,
    parse_active_window_id,
    parse_window_pid,
)

ROOT_OK = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4a00007\n"
PID_OK = "_NET_WM_PID(CARDINAL) = 12345\n"


class FakeRunner:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[Sequence[str], dict[str, Any]]] = []

    def __call__(self, args: Sequence[str], **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def done(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout)


def make_reader(
    runner: FakeRunner,
    *,
    enabled: bool = True,
    session_type: str | None = "x11",
    xprop: str | None = "/usr/bin/xprop",
) -> ForegroundReader:
    return ForegroundReader(
        enabled=enabled,
        session_type=session_type,
        which=lambda name: xprop,
        runner=runner,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (ROOT_OK, 0x4A00007),
        ("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n", None),
        ("_NET_ACTIVE_WINDOW:  not found.\n", None),
        ("", None),
        ("garbage window id # zz\n", None),
    ],
)
def test_parse_active_window_id(text: str, expected: int | None) -> None:
    assert parse_active_window_id(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PID_OK, 12345),
        ("_NET_WM_PID(CARDINAL) = 0\n", None),
        ("_NET_WM_PID:  not found.\n", None),
        ("_NET_WM_PID(CARDINAL) = abc\n", None),
        ("", None),
    ],
)
def test_parse_window_pid(text: str, expected: int | None) -> None:
    assert parse_window_pid(text) == expected


def test_read_returns_pid_with_two_safe_xprop_calls() -> None:
    runner = FakeRunner(done(ROOT_OK), done(PID_OK))
    state = make_reader(runner).read()
    assert state == ForegroundState(status=ForegroundStatus.ACTIVE, pid=12345)
    assert [call[0] for call in runner.calls] == [
        ["/usr/bin/xprop", "-root", "_NET_ACTIVE_WINDOW"],
        ["/usr/bin/xprop", "-id", "0x4a00007", "_NET_WM_PID"],
    ]
    for _, kwargs in runner.calls:
        assert kwargs["check"] is False
        assert kwargs["timeout"] > 0
        assert not kwargs.get("shell")
        assert "env" not in kwargs


def test_wayland_is_disabled_without_spawning_processes() -> None:
    runner = FakeRunner()
    state = make_reader(runner, session_type="wayland").read()
    assert state.status is ForegroundStatus.DISABLED
    assert state.pid is None
    assert runner.calls == []


def test_x11_spawns_processes_paired_with_wayland_case() -> None:
    runner = FakeRunner(done(ROOT_OK), done(PID_OK))
    assert make_reader(runner).read().status is ForegroundStatus.ACTIVE
    assert len(runner.calls) == 2


@pytest.mark.parametrize("session_type", [None, "", "tty"])
def test_non_x11_session_is_disabled(session_type: str | None) -> None:
    runner = FakeRunner()
    state = make_reader(runner, session_type=session_type).read()
    assert state.status is ForegroundStatus.DISABLED
    assert runner.calls == []


def test_config_flag_off_is_disabled() -> None:
    runner = FakeRunner()
    state = make_reader(runner, enabled=False).read()
    assert state.status is ForegroundStatus.DISABLED
    assert runner.calls == []


def test_missing_xprop_is_disabled() -> None:
    runner = FakeRunner()
    state = make_reader(runner, xprop=None).read()
    assert state.status is ForegroundStatus.DISABLED
    assert runner.calls == []


def test_xprop_path_resolved_once() -> None:
    lookups: list[str] = []

    def which(name: str) -> str:
        lookups.append(name)
        return "/usr/bin/xprop"

    runner = FakeRunner(done(ROOT_OK), done(PID_OK), done(ROOT_OK), done(PID_OK))
    reader = ForegroundReader(enabled=True, session_type="x11", which=which, runner=runner)
    reader.read()
    reader.read()
    assert lookups == ["xprop"]


@pytest.mark.parametrize(
    "replies",
    [
        [subprocess.TimeoutExpired(cmd="xprop", timeout=1)],
        [OSError("boom")],
        [done("", returncode=1)],
        [done("strange output\n")],
        [done("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n")],
        [done(ROOT_OK), subprocess.TimeoutExpired(cmd="xprop", timeout=1)],
        [done(ROOT_OK), done("", returncode=1)],
        [done(ROOT_OK), done("_NET_WM_PID:  not found.\n")],
        [done(ROOT_OK), done(PID_OK, returncode=3)],
        [done(ROOT_OK), subprocess.CompletedProcess(args=[], returncode=0, stdout=None)],
    ],
)
def test_failures_are_unavailable_never_raise(replies: list[Any]) -> None:
    state = make_reader(FakeRunner(*replies)).read()
    assert state == ForegroundState(status=ForegroundStatus.UNAVAILABLE, pid=None)
