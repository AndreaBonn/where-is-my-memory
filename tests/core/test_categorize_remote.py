from dataclasses import replace

import pytest

from wimm.core.categorize import CategorizationContext, categorize_process
from wimm.model.enums import Category, Protection, protection_of
from wimm.model.raw import RawProcess

from .helpers import process

SSH_SCOPE = "/user.slice/user-1000.slice/session-5.scope"
SSHD_PID = 500
SHELL_PID = 501
SERVER_PID = 502
SERVER_PORT = 5173


def ssh_process(*, pid: int, ppid: int, name: str, uid: int = 1000) -> RawProcess:
    return process(pid=pid, ppid=ppid, name=name, uid=uid, cgroup=SSH_SCOPE)


def session_tree() -> dict[int, RawProcess]:
    processes = [
        ssh_process(pid=SSHD_PID, ppid=1, name="sshd"),
        ssh_process(pid=SHELL_PID, ppid=SSHD_PID, name="bash"),
        ssh_process(pid=SERVER_PID, ppid=SHELL_PID, name="node"),
        ssh_process(pid=503, ppid=1, name="tmux: server"),
        ssh_process(pid=504, ppid=SHELL_PID, name="vim"),
        ssh_process(pid=505, ppid=SHELL_PID, name="node", uid=1001),
        ssh_process(pid=506, ppid=1, name="sshd-session"),
        ssh_process(pid=507, ppid=1, name="SCREEN"),
        ssh_process(pid=508, ppid=SHELL_PID, name="bash"),
    ]
    return {item.pid: item for item in processes}


def context(*, remote: bool) -> CategorizationContext:
    return CategorizationContext(
        own_uid=1000,
        own_pid=999,
        processes=session_tree(),
        listen_ports_by_pid={SERVER_PID: frozenset({SERVER_PORT})},
        extra_protected_names=(),
        desktop_categories={},
        remote_sessions_actionable=remote,
    )


def decide(*, pid: int, remote: bool) -> Category | None:
    ctx = context(remote=remote)
    return categorize_process(proc=ctx.processes[pid], context=ctx).category


def is_protected(*, pid: int, remote: bool) -> bool:
    category = decide(pid=pid, remote=remote)
    return category is None or protection_of(category=category) is Protection.PROTECTED


def test_remote_session_off_protects_every_process_of_the_session() -> None:
    assert all(is_protected(pid=pid, remote=False) for pid in session_tree())


def test_remote_session_on_makes_a_dev_server_actionable() -> None:
    assert decide(pid=SERVER_PID, remote=True) is Category.DEV_SERVER
    assert not is_protected(pid=SERVER_PID, remote=True)


def test_remote_session_on_applies_the_normal_rules_to_other_user_processes() -> None:
    assert decide(pid=504, remote=True) is Category.DEV_PROCESS


@pytest.mark.parametrize("pid", [SSHD_PID, 506])
def test_remote_session_on_keeps_sshd_protected(pid: int) -> None:
    assert is_protected(pid=pid, remote=True)


def test_remote_session_on_keeps_the_login_shell_protected() -> None:
    assert is_protected(pid=SHELL_PID, remote=True)


def test_remote_session_on_leaves_a_nested_shell_to_the_normal_rules() -> None:
    assert not is_protected(pid=508, remote=True)


@pytest.mark.parametrize("pid", [503, 507])
def test_remote_session_on_keeps_the_multiplexer_server_protected(pid: int) -> None:
    assert is_protected(pid=pid, remote=True)


def test_remote_session_on_never_opens_the_process_of_another_user() -> None:
    assert decide(pid=505, remote=True) is Category.SYSTEM


def test_remote_session_on_does_not_touch_other_system_cgroups() -> None:
    ctx = replace(context(remote=True), processes={})
    proc = process(pid=600, cgroup="/system.slice/cron.service")
    assert categorize_process(proc=proc, context=ctx).category is Category.SYSTEM
