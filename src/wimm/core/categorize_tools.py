from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from wimm.model.enums import Category
from wimm.model.raw import RawProcess

from .cgroup_paths import basename as _basename
from .cgroup_paths import components as _components
from .cgroup_paths import matches as _matches
from .cgroup_paths import scope_appid as _scope_appid
from .constants import (
    AI_CLI_NAMES,
    BROWSER_NAMES,
    BROWSER_SCOPE_PATTERNS,
    CLI_WRAPPER_NAMES,
    DOCUMENT_APP_NAMES,
    OLLAMA_NAME,
    OLLAMA_RUN_COMMAND,
    OPTION_PREFIX,
    PODMAN_CONMON_PREFIX,
    PODMAN_SCOPE_PATTERNS,
    PODMAN_SCOPE_PREFIX,
    REASON_AI_CLI,
    REASON_DOCUMENT_APP_FROM_TERMINAL,
    REASON_LISTEN,
    REASON_SCOPE,
    REASON_TERMINAL_PROCESS,
    SCOPE_SUFFIX,
    SHELL_NAMES,
    TERMINAL_APPIDS,
    TERMINAL_NAMES,
    VTE_SCOPE_PATTERNS,
)


@dataclass(frozen=True, slots=True)
class CategoryDecision:
    category: Category | None
    reason_code: str
    appid: str | None = None
    scope: str | None = None
    inherited_from: int | None = None


@dataclass(frozen=True, slots=True)
class CategorizationContext:
    own_uid: int
    own_pid: int
    processes: Mapping[int, RawProcess]
    listen_ports_by_pid: Mapping[int, frozenset[int]]
    extra_protected_names: tuple[str, ...]
    desktop_categories: Mapping[str, tuple[str, ...]]
    # Ids of the containers the engine API lists; empty when it is not reachable. A
    # `libpod-*.scope` process is dropped only if its container is in here.
    engine_container_ids: frozenset[str] = frozenset()


def libpod_container_id(proc: RawProcess) -> str | None:
    """Container id named by a Podman scope (container or conmon) of the process, if any."""
    for part in _components(proc=proc):
        if _matches(name=part, patterns=PODMAN_SCOPE_PATTERNS):
            name = part.removeprefix(PODMAN_SCOPE_PREFIX).removeprefix(PODMAN_CONMON_PREFIX)
            return name.removesuffix(SCOPE_SUFFIX)
    return None


def ancestors(proc: RawProcess, context: CategorizationContext) -> Iterator[RawProcess]:
    seen = {proc.pid}
    parent = context.processes.get(proc.ppid)
    while parent is not None and parent.pid not in seen:
        yield parent
        seen.add(parent.pid)
        parent = context.processes.get(parent.ppid)


def process_names(proc: RawProcess) -> tuple[str, ...]:
    paths = (proc.exe, *(proc.cmdline or ())[:1])
    return (proc.name, *(_basename(path) for path in paths if path))


def is_terminal(proc: RawProcess) -> bool:
    return any(name in TERMINAL_NAMES for name in process_names(proc=proc))


def scope_decision(proc: RawProcess) -> CategoryDecision | None:
    parts = _components(proc=proc)
    scope = parts[-1] if parts else ""
    appid = _scope_appid(scope=scope)
    executable = _basename(proc.exe) if proc.exe else proc.name
    if (
        _matches(name=scope, patterns=BROWSER_SCOPE_PATTERNS)
        or proc.name in BROWSER_NAMES
        or executable in BROWSER_NAMES
    ):
        return CategoryDecision(
            category=Category.BROWSER,
            reason_code=REASON_SCOPE,
            appid=appid or proc.name,
            scope=scope,
        )
    if appid in TERMINAL_APPIDS or is_terminal(proc=proc):
        return CategoryDecision(
            category=Category.TERMINAL, reason_code=REASON_SCOPE, appid=appid, scope=scope
        )
    document = _document_app_decision(proc=proc, scope=scope)
    if document is not None:
        return document
    if appid is not None:
        return CategoryDecision(
            category=Category.DESKTOP_APP, reason_code=REASON_SCOPE, appid=appid, scope=scope
        )
    return None


def _document_app_decision(proc: RawProcess, scope: str) -> CategoryDecision | None:
    if _in_vte_scope(proc=proc):
        for name in process_names(proc=proc):
            if name in DOCUMENT_APP_NAMES:
                return CategoryDecision(
                    category=Category.DESKTOP_APP,
                    reason_code=REASON_DOCUMENT_APP_FROM_TERMINAL,
                    appid=name,
                    scope=scope,
                )
    return None


def _in_vte_scope(proc: RawProcess) -> bool:
    return any(_matches(name=part, patterns=VTE_SCOPE_PATTERNS) for part in _components(proc=proc))


def _from_terminal(proc: RawProcess, context: CategorizationContext) -> bool:
    if _in_vte_scope(proc=proc):
        return True
    return any(parent.name in SHELL_NAMES for parent in ancestors(proc=proc, context=context))


def _is_ai_cli(proc: RawProcess) -> bool:
    args = proc.cmdline or ()
    names = tuple(_basename(arg) for arg in args)
    if proc.name in AI_CLI_NAMES or (names and names[0] in AI_CLI_NAMES):
        return True
    if names and names[0] in CLI_WRAPPER_NAMES:
        script = next((arg for arg in args[1:] if not arg.startswith(OPTION_PREFIX)), "")
        return _basename(script) in AI_CLI_NAMES
    return len(names) >= 2 and names[0] == OLLAMA_NAME and args[1] == OLLAMA_RUN_COMMAND


def rule_ai_cli(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    if _from_terminal(proc=proc, context=context) and _is_ai_cli(proc=proc):
        return CategoryDecision(category=Category.AI_CLI, reason_code=REASON_AI_CLI)
    return None


def rule_listen(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    if context.listen_ports_by_pid.get(proc.pid):
        return CategoryDecision(category=Category.DEV_SERVER, reason_code=REASON_LISTEN)
    return None


def rule_terminal_process(
    proc: RawProcess, context: CategorizationContext
) -> CategoryDecision | None:
    if _from_terminal(proc=proc, context=context):
        return CategoryDecision(category=Category.DEV_PROCESS, reason_code=REASON_TERMINAL_PROCESS)
    return None
