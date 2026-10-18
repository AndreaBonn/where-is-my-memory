import pytest

from wimm.core.categorize import CategorizationContext, categorize_process
from wimm.model.enums import Category, Protection, protection_of
from wimm.model.raw import RawProcess

from .helpers import process

LOCAL_SCOPE = "/user.slice/user-1000.slice/session-2.scope"
REMOTE_SCOPE = "/user.slice/user-1000.slice/session-7.scope"
MOSH_SCOPE = "/user.slice/user-1000.slice/session-9.scope"
SERVER_PORT = 5173


def tree(*items: RawProcess) -> dict[int, RawProcess]:
    return {item.pid: item for item in items}


def decide(*, processes: dict[int, RawProcess], pid: int) -> Category | None:
    context = CategorizationContext(
        own_uid=1000,
        own_pid=999,
        processes=processes,
        listen_ports_by_pid={pid: frozenset({SERVER_PORT})},
        extra_protected_names=(),
        desktop_categories={},
        remote_sessions_actionable=True,
    )
    return categorize_process(proc=processes[pid], context=context).category


def is_protected(*, processes: dict[int, RawProcess], pid: int) -> bool:
    category = decide(processes=processes, pid=pid)
    return category is None or protection_of(category=category) is Protection.PROTECTED


@pytest.mark.parametrize("name", ["gdm-wayland-session", "(sd-pam)", "node"])
def test_local_login_scope_without_sshd_stays_protected_with_the_option_on(name: str) -> None:
    processes = tree(
        process(pid=100, name="gdm-session-wor", cgroup=LOCAL_SCOPE),
        process(pid=101, ppid=100, name=name, cgroup=LOCAL_SCOPE),
    )

    assert is_protected(processes=processes, pid=101)


def test_scope_with_sshd_makes_its_dev_server_actionable() -> None:
    processes = tree(
        process(pid=200, name="sshd-session", cgroup=REMOTE_SCOPE),
        process(pid=201, ppid=200, name="node", cgroup=REMOTE_SCOPE),
    )

    assert decide(processes=processes, pid=201) is Category.DEV_SERVER
    assert not is_protected(processes=processes, pid=201)


def test_sshd_named_only_in_its_command_line_marks_the_scope_remote() -> None:
    processes = tree(
        process(pid=210, name="sshd", cmdline=("sshd: bonn@pts/0",), cgroup=REMOTE_SCOPE),
        process(pid=211, ppid=210, name="node", cgroup=REMOTE_SCOPE),
    )

    assert not is_protected(processes=processes, pid=211)


def test_sshd_in_another_scope_does_not_open_a_local_scope() -> None:
    processes = tree(
        process(pid=200, name="sshd-session", cgroup=REMOTE_SCOPE),
        process(pid=300, name="gdm-session-wor", cgroup=LOCAL_SCOPE),
        process(pid=301, ppid=300, name="node", cgroup=LOCAL_SCOPE),
    )

    assert is_protected(processes=processes, pid=301)


def test_mosh_scope_protects_mosh_server_and_opens_its_child() -> None:
    processes = tree(
        process(pid=400, name="mosh-server", cgroup=MOSH_SCOPE),
        process(pid=401, ppid=400, name="node", cgroup=MOSH_SCOPE),
    )

    assert is_protected(processes=processes, pid=400)
    assert not is_protected(processes=processes, pid=401)


def test_mosh_server_is_protected_even_with_the_option_off() -> None:
    processes = tree(process(pid=400, name="mosh-server", cgroup=MOSH_SCOPE))
    context = CategorizationContext(
        own_uid=1000,
        own_pid=999,
        processes=processes,
        listen_ports_by_pid={},
        extra_protected_names=(),
        desktop_categories={},
    )

    category = categorize_process(proc=processes[400], context=context).category

    assert category is not None
    assert protection_of(category=category) is Protection.PROTECTED


@pytest.mark.parametrize("shell", ["tcsh", "csh", "ksh", "nu"])
def test_login_shell_of_any_known_shell_stays_protected(shell: str) -> None:
    processes = tree(
        process(pid=500, name="sshd-session", cgroup=REMOTE_SCOPE),
        process(pid=501, ppid=500, name=shell, cgroup=REMOTE_SCOPE),
        process(pid=502, ppid=501, name=shell, cgroup=REMOTE_SCOPE),
    )

    assert is_protected(processes=processes, pid=501)
    assert not is_protected(processes=processes, pid=502)


def test_login_shell_under_mosh_server_stays_protected() -> None:
    processes = tree(
        process(pid=600, name="mosh-server", cgroup=MOSH_SCOPE),
        process(pid=601, ppid=600, name="bash", cgroup=MOSH_SCOPE),
    )

    assert is_protected(processes=processes, pid=601)
