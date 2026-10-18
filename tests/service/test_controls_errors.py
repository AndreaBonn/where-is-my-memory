"""Error paths of the real controls: what a process or container that vanishes or refuses does."""

import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import docker.errors
import psutil
import pytest

from tests.integration.live_targets import (
    PARENT_SCRIPT,
    python_child,
    spawned,
    wait_ready,
)
from tests.service.engine_fakes import FakeProvider, engine_at
from wimm.service.controls import DockerSdkControl, PsutilProcessControl
from wimm.service.errors import ControlFailed

SLEEP = ["sleep", "30"]
EXIT_WAIT_S = 10
SOCKET = "/var/run/docker.sock"


def _raising(error: Exception) -> Callable[..., object]:
    def raiser(*_: object, **__: object) -> object:
        raise error

    return raiser


def _dead_pid() -> int:
    child = subprocess.Popen(args=[sys.executable, "-c", "pass"])
    child.wait(timeout=EXIT_WAIT_S)
    return child.pid


@dataclass(frozen=True, slots=True)
class _Parent:
    pid: int


class _StubProcess:
    """What `_is_protected` reads from a psutil process: the own pid and the parents."""

    def __init__(self, *, pid: int, parent_pid: int) -> None:
        self.pid = pid
        self._parent = _Parent(pid=parent_pid)

    def parents(self) -> list[_Parent]:
        return [self._parent]


@pytest.mark.parametrize("parent_alive", [True, False], ids=["parent-alive", "parent-vanished"])
def test_chain_with_a_pid_that_vanished_while_reading_it_is_incomplete(
    parent_alive: bool, caplog: pytest.LogCaptureFixture
) -> None:
    parent_pid = os.getppid() if parent_alive else _dead_pid()
    stub = _StubProcess(pid=os.getpid(), parent_pid=parent_pid)
    control = PsutilProcessControl(owner_uid=os.getuid())

    with caplog.at_level(logging.DEBUG, logger="wimm.service.controls"):
        protected = control._is_protected(process=stub)  # type: ignore[arg-type]

    assert ("incomplete" in caplog.text) is (not parent_alive)
    if not parent_alive:
        assert protected is True


def test_inspect_failing_with_a_psutil_error_is_control_failed_and_not_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=SLEEP) as child:
        with monkeypatch.context() as patch:
            patch.setattr(
                psutil.Process, "create_time", _raising(psutil.AccessDenied(pid=child.pid))
            )
            with pytest.raises(ControlFailed, match=f"Cannot inspect process {child.pid}"):
                control.inspect(pid=child.pid)
            with pytest.raises(ControlFailed, match="not inspected"):
                control.send_signal(pid=child.pid, sig=signal.SIGTERM)

        live = control.inspect(pid=child.pid)
        assert live is not None and live.pid == child.pid


def test_inspect_of_a_process_that_vanishes_midway_is_none_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=SLEEP) as child:
        with monkeypatch.context() as patch:
            patch.setattr(
                psutil.Process, "create_time", _raising(psutil.NoSuchProcess(pid=child.pid))
            )
            assert control.inspect(pid=child.pid) is None

        assert control.inspect(pid=child.pid) is not None


def test_cmdline_denied_is_an_empty_tuple_while_a_readable_one_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=SLEEP) as child:
        readable = control.inspect(pid=child.pid)
        monkeypatch.setattr(psutil.Process, "cmdline", _raising(psutil.AccessDenied(pid=child.pid)))

        denied = control.inspect(pid=child.pid)

    assert readable is not None and readable.cmdline == ("sleep", "30")
    assert denied is not None and denied.cmdline == ()


@pytest.fixture
def parent_with_one_child() -> Iterator[subprocess.Popen[str]]:
    with spawned(args=python_child(script=PARENT_SCRIPT)) as parent:
        wait_ready(child=parent)
        yield parent


def test_descendants_lists_the_children_of_a_live_parent(
    parent_with_one_child: subprocess.Popen[str],
) -> None:
    pids = PsutilProcessControl(owner_uid=os.getuid()).descendants(pid=parent_with_one_child.pid)

    assert [psutil.Process(pid).name() for pid in pids] == ["sleep"]


def test_descendants_of_a_pid_that_is_gone_is_empty() -> None:
    assert PsutilProcessControl(owner_uid=os.getuid()).descendants(pid=_dead_pid()) == ()


def test_descendants_failing_with_a_psutil_error_is_control_failed(
    parent_with_one_child: subprocess.Popen[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = parent_with_one_child.pid
    monkeypatch.setattr(psutil.Process, "children", _raising(psutil.AccessDenied(pid=pid)))

    with pytest.raises(ControlFailed, match=f"Cannot list children of {pid}"):
        PsutilProcessControl(owner_uid=os.getuid()).descendants(pid=pid)


def test_signal_to_a_process_that_vanished_is_silent_and_a_denied_one_is_control_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=SLEEP) as child:
        assert control.inspect(pid=child.pid) is not None
        with monkeypatch.context() as patch:
            patch.setattr(
                psutil.Process, "send_signal", _raising(psutil.NoSuchProcess(pid=child.pid))
            )
            control.send_signal(pid=child.pid, sig=signal.SIGTERM)
            patch.setattr(
                psutil.Process, "send_signal", _raising(psutil.AccessDenied(pid=child.pid))
            )
            with pytest.raises(ControlFailed, match=f"Cannot signal process {child.pid}"):
                control.send_signal(pid=child.pid, sig=signal.SIGTERM)

        assert child.poll() is None
        control.send_signal(pid=child.pid, sig=signal.SIGTERM)
        assert child.wait(timeout=EXIT_WAIT_S) == -signal.SIGTERM


@dataclass(slots=True)
class _VanishingContainer:
    """A container whose state cannot be read: the SDK raises `error` on `.status`."""

    id: str
    error: Exception | None = None

    @property
    def status(self) -> str:
        if self.error is not None:
            raise self.error
        return "running"


@dataclass(slots=True)
class _Containers:
    held: dict[str, _VanishingContainer]

    def get(self, container_id: str) -> _VanishingContainer:
        return self.held[container_id]


@dataclass(slots=True)
class _Client:
    containers: _Containers


def _docker(*, container: _VanishingContainer) -> DockerSdkControl:
    client = _Client(containers=_Containers(held={container.id: container}))
    return DockerSdkControl(engines=FakeProvider(engines=(engine_at(path=SOCKET, client=client),)))


def test_container_that_vanishes_after_the_lookup_is_none_and_a_present_one_is_live() -> None:
    gone = _VanishingContainer(id="c1", error=docker.errors.NotFound("removed meanwhile"))

    assert _docker(container=gone).inspect(container_id="c1") is None
    live = _docker(container=_VanishingContainer(id="c1")).inspect(container_id="c1")
    assert live is not None and live.status == "running"


def test_container_state_unreadable_with_an_sdk_error_is_control_failed() -> None:
    broken = _VanishingContainer(id="c1", error=docker.errors.APIError("daemon down"))

    with pytest.raises(ControlFailed, match=r"Cannot inspect container.*daemon down"):
        _docker(container=broken).inspect(container_id="c1")
