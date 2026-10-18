"""Login-session processes (``session-*.scope``) that the user may opt in to manage (R28).

logind puts every login in a scope outside ``user@UID.service``, so they are protected
as SYSTEM by default (Q-12). A scope counts as remote only if an sshd or a mosh-server
runs in it: local TTY and display-manager sessions stay protected. With the option on,
the user's own processes in a remote scope follow the normal rules, except the ones the
connection itself depends on.
"""

from collections.abc import Iterable, Mapping

from wimm.model.raw import RawProcess

from .cgroup_paths import basename as _basename
from .cgroup_paths import components as _components
from .cgroup_paths import matches as _matches
from .constants import (
    LOGIN_INFRASTRUCTURE_NAMES,
    LOGIN_SESSION_SCOPE_PATTERNS,
    MOSH_SERVER_PATTERNS,
    SHELL_NAMES,
    SSHD_NAME_PATTERNS,
)

LOGIN_LEADER_PATTERNS = SSHD_NAME_PATTERNS + MOSH_SERVER_PATTERNS


def _names(proc: RawProcess) -> tuple[str, ...]:
    first = (proc.cmdline or ("",))[0]
    return (proc.name, _basename(first)) if first else (proc.name,)


def _session_scopes(proc: RawProcess) -> tuple[str, ...]:
    return tuple(
        part
        for part in _components(proc=proc)
        if _matches(name=part, patterns=LOGIN_SESSION_SCOPE_PATTERNS)
    )


def remote_login_scopes(processes: Iterable[RawProcess]) -> frozenset[str]:
    """Names of the ``session-*.scope`` units that hold an sshd or a mosh-server."""
    return frozenset(
        scope
        for proc in processes
        if any(_matches(name=name, patterns=LOGIN_LEADER_PATTERNS) for name in _names(proc))
        for scope in _session_scopes(proc)
    )


def in_remote_session(proc: RawProcess, scopes: frozenset[str]) -> bool:
    """Return whether the process runs in one of the remote login ``scopes``."""
    return any(scope in scopes for scope in _session_scopes(proc))


def is_login_infrastructure(proc: RawProcess, processes: Mapping[int, RawProcess]) -> bool:
    """Return whether the process holds the remote connection up: sshd, login shell, tmux/screen.

    ``RawProcess`` carries no session id, so the login shell is the shell whose direct
    parent is sshd or mosh-server. A shell started from another shell is an ordinary process.
    """
    if _matches(name=proc.name, patterns=LOGIN_LEADER_PATTERNS + LOGIN_INFRASTRUCTURE_NAMES):
        return True
    parent = processes.get(proc.ppid)
    return (
        proc.name in SHELL_NAMES
        and parent is not None
        and _matches(name=parent.name, patterns=LOGIN_LEADER_PATTERNS)
    )
