import logging
from pathlib import Path
from typing import cast

import psutil
import pytest

from tests.core.helpers import process
from wimm.collectors import CollectorResult
from wimm.config import Config
from wimm.service import compose, controls
from wimm.service.build_actions import build_actions
from wimm.service.controls import PsutilProcessControl
from wimm.service.errors import ControlFailed

SSH_SCOPE = "/user.slice/user-1000.slice/session-5.scope"
OWNER_UID = 1000
SSHD_PID = 10
SERVER_PID = 20


class StubParent:
    pid = SSHD_PID


class StubServer:
    pid = SERVER_PID

    def parents(self) -> list[StubParent]:
        return [StubParent()]


def _first_plan_protects_the_ssh_dev_server(
    *, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: bool
) -> bool:
    sshd = process(pid=SSHD_PID, name="sshd", cgroup=SSH_SCOPE)
    server = process(pid=SERVER_PID, ppid=SSHD_PID, name="node", cgroup=SSH_SCOPE)
    monkeypatch.setattr(
        controls, "collect_processes", lambda **_: CollectorResult(data=(sshd, server))
    )
    setup = build_actions(
        config=Config(remote_sessions_actionable=enabled), owner_uid=OWNER_UID, home=tmp_path
    )
    control: PsutilProcessControl = setup.executor.processes
    return control._is_protected(process=cast(psutil.Process, StubServer()))


def test_build_actions_with_the_option_on_makes_ssh_processes_actionable_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    protected = _first_plan_protects_the_ssh_dev_server(
        monkeypatch=monkeypatch, tmp_path=tmp_path, enabled=True
    )

    assert protected is False


def test_build_actions_with_the_option_off_keeps_ssh_processes_protected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    protected = _first_plan_protects_the_ssh_dev_server(
        monkeypatch=monkeypatch, tmp_path=tmp_path, enabled=False
    )

    assert protected is True


def test_without_the_docker_cli_project_actions_are_disabled_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def missing(**_: object) -> str:
        raise ControlFailed("The docker command was not found in PATH: compose is unavailable")

    monkeypatch.setattr(compose, "resolve_docker_binary", missing)

    with caplog.at_level(logging.WARNING, logger="wimm.service.build_actions"):
        setup = build_actions(config=Config(), owner_uid=OWNER_UID, home=tmp_path)

    assert setup.executor.compose is None
    assert [r.getMessage() for r in caplog.records if r.name == "wimm.service.build_actions"] == [
        "Docker compose unavailable, project actions disabled"
    ]
    assert setup.executor.containers is not None  # the rest of the executor is still built


def test_with_the_docker_cli_project_actions_are_enabled_without_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(compose, "resolve_docker_binary", lambda **_: "/usr/bin/docker")

    with caplog.at_level(logging.WARNING, logger="wimm.service.build_actions"):
        setup = build_actions(config=Config(), owner_uid=OWNER_UID, home=tmp_path)

    assert setup.executor.compose is not None
    assert [r for r in caplog.records if r.name == "wimm.service.build_actions"] == []
