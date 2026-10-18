from dataclasses import replace
from typing import cast

import psutil
import pytest

from tests.core.helpers import process
from wimm.collectors import CollectorResult
from wimm.service import controls
from wimm.service.controls import PsutilProcessControl

SSH_SCOPE = "/user.slice/user-1000.slice/session-5.scope"
OWNER_UID = 1000


class StubProcess:
    """The two things `_is_protected` reads from a psutil process."""

    pid = 20

    def parents(self) -> list["StubParent"]:
        return [StubParent()]


class StubParent:
    pid = 10


def _protected(*, monkeypatch: pytest.MonkeyPatch, enabled: bool) -> bool:
    dev_server = process(pid=20, name="node", cgroup=SSH_SCOPE)
    sshd = process(pid=10, name="sshd", cgroup=SSH_SCOPE)
    dev_server = replace(dev_server, ppid=10)
    monkeypatch.setattr(
        controls, "collect_processes", lambda **_: CollectorResult(data=(sshd, dev_server))
    )
    control = PsutilProcessControl(owner_uid=OWNER_UID)
    control.set_remote_sessions_actionable(enabled=enabled)
    return control._is_protected(process=cast(psutil.Process, StubProcess()))


def test_ssh_session_process_is_protected_at_action_time_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _protected(monkeypatch=monkeypatch, enabled=False) is True


def test_ssh_session_process_is_actionable_at_action_time_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _protected(monkeypatch=monkeypatch, enabled=True) is False
