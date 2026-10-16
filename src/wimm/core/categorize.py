from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from wimm.model.enums import Category
from wimm.model.raw import RawProcess

from .cgroup_paths import components as _components
from .cgroup_paths import is_direct_user_service
from .cgroup_paths import matches as _matches
from .cgroup_paths import scope_appid as _scope_appid
from .constants import (
    AI_CLI_NAMES,
    BROWSER_NAMES,
    BROWSER_SCOPE_PATTERNS,
    CLI_WRAPPER_NAMES,
    DBUS_NAME_PREFIX,
    DOCKER_SCOPE_PATTERNS,
    DOCUMENT_APP_NAMES,
    DOCUMENT_DESKTOP_CATEGORIES,
    OLLAMA_NAME,
    OLLAMA_RUN_COMMAND,
    OPTION_PREFIX,
    PROTECTED_PROCESS_NAMES,
    REASON_AI_CLI,
    REASON_ANCESTOR,
    REASON_DOCUMENT_APP_FROM_TERMINAL,
    REASON_EXCLUDED,
    REASON_LISTEN,
    REASON_OTHER,
    REASON_PROTECTED_NAME,
    REASON_SCOPE,
    REASON_SELF,
    REASON_SESSION,
    REASON_SYSTEM,
    REASON_TERMINAL_PROCESS,
    REASON_USER_SERVICE,
    SERVICE_SUFFIX,
    SESSION_SERVICE_PATTERNS,
    SESSION_SLICE,
    SHELL_NAMES,
    SYSTEMD_NAME,
    SYSTEMD_USER_FLAG,
    TERMINAL_APPIDS,
    TERMINAL_NAMES,
    USER_UNIT_TEMPLATE,
    VTE_SCOPE_PATTERNS,
)

INHERITED_CATEGORIES = (Category.BROWSER, Category.DESKTOP_APP)


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


def _ancestors(proc: RawProcess, context: CategorizationContext) -> Iterator[RawProcess]:
    seen = {proc.pid}
    parent = context.processes.get(proc.ppid)
    while parent is not None and parent.pid not in seen:
        yield parent
        seen.add(parent.pid)
        parent = context.processes.get(parent.ppid)


def _early_decision(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    parts = _components(proc=proc)
    if proc.pid == context.own_pid:
        return CategoryDecision(category=Category.SELF, reason_code=REASON_SELF)
    if any(_matches(name=part, patterns=DOCKER_SCOPE_PATTERNS) for part in parts):
        return CategoryDecision(category=None, reason_code=REASON_EXCLUDED)
    if proc.uid != context.own_uid or USER_UNIT_TEMPLATE.format(uid=context.own_uid) not in parts:
        return CategoryDecision(category=Category.SYSTEM, reason_code=REASON_SYSTEM)
    if _is_session(proc=proc):
        return CategoryDecision(category=Category.SESSION, reason_code=REASON_SESSION)
    if any(
        _matches(name=name, patterns=PROTECTED_PROCESS_NAMES + context.extra_protected_names)
        for name in _process_names(proc=proc)
    ):
        return CategoryDecision(category=Category.SESSION, reason_code=REASON_PROTECTED_NAME)
    if is_direct_user_service(proc=proc) and not _is_terminal(proc=proc):
        return CategoryDecision(category=Category.OTHER, reason_code=REASON_USER_SERVICE)
    return None


def _is_session(proc: RawProcess) -> bool:
    parts = _components(proc=proc)
    if (SESSION_SLICE in parts and not is_direct_user_service(proc=proc)) or proc.name.startswith(
        DBUS_NAME_PREFIX
    ):
        return True
    if proc.name == SYSTEMD_NAME and SYSTEMD_USER_FLAG in (proc.cmdline or ()):
        return True
    if not parts or not parts[-1].endswith(SERVICE_SUFFIX):
        return False
    service = parts[-1].removesuffix(SERVICE_SUFFIX)
    return _matches(name=service, patterns=SESSION_SERVICE_PATTERNS)


def _process_names(proc: RawProcess) -> tuple[str, ...]:
    paths = (proc.exe, *(proc.cmdline or ())[:1])
    return (proc.name, *(PurePosixPath(path).name for path in paths if path))


def _is_terminal(proc: RawProcess) -> bool:
    return any(name in TERMINAL_NAMES for name in _process_names(proc=proc))


def _scope_decision(proc: RawProcess) -> CategoryDecision | None:
    parts = _components(proc=proc)
    scope = parts[-1] if parts else ""
    appid = _scope_appid(scope=scope)
    executable = PurePosixPath(proc.exe).name if proc.exe else proc.name
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
    if appid in TERMINAL_APPIDS or _is_terminal(proc=proc):
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
        for name in _process_names(proc=proc):
            if name in DOCUMENT_APP_NAMES:
                return CategoryDecision(
                    category=Category.DESKTOP_APP,
                    reason_code=REASON_DOCUMENT_APP_FROM_TERMINAL,
                    appid=name,
                    scope=scope,
                )
    return None


def _app_decision(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    direct = _scope_decision(proc=proc)
    if direct is not None:
        return direct
    for ancestor in _ancestors(proc=proc, context=context):
        if _early_decision(proc=ancestor, context=context) is not None:
            continue
        decision = _scope_decision(proc=ancestor)
        if decision is not None and decision.category in INHERITED_CATEGORIES:
            return CategoryDecision(
                category=decision.category,
                reason_code=REASON_ANCESTOR,
                appid=decision.appid,
                scope=decision.scope,
                inherited_from=ancestor.pid,
            )
    return None


def is_terminal_shell(proc: RawProcess) -> bool:
    """Identify shells to group with their terminal without offering own actions.

    Parameters
    ----------
    proc : RawProcess
        Process whose name and cgroup are inspected without I/O.
    """
    return proc.name in SHELL_NAMES and any(
        _matches(name=part, patterns=VTE_SCOPE_PATTERNS) for part in _components(proc=proc)
    )


def _in_vte_scope(proc: RawProcess) -> bool:
    return any(_matches(name=part, patterns=VTE_SCOPE_PATTERNS) for part in _components(proc=proc))


def _from_terminal(proc: RawProcess, context: CategorizationContext) -> bool:
    if _in_vte_scope(proc=proc):
        return True
    return any(parent.name in SHELL_NAMES for parent in _ancestors(proc=proc, context=context))


def _is_ai_cli(proc: RawProcess) -> bool:
    args = proc.cmdline or ()
    names = tuple(PurePosixPath(arg).name for arg in args)
    if proc.name in AI_CLI_NAMES or (names and names[0] in AI_CLI_NAMES):
        return True
    if names and names[0] in CLI_WRAPPER_NAMES:
        script = next((arg for arg in args[1:] if not arg.startswith(OPTION_PREFIX)), "")
        return PurePosixPath(script).name in AI_CLI_NAMES
    return len(names) >= 2 and names[0] == OLLAMA_NAME and args[1] == OLLAMA_RUN_COMMAND


def _rule_ai_cli(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    if _from_terminal(proc=proc, context=context) and _is_ai_cli(proc=proc):
        return CategoryDecision(category=Category.AI_CLI, reason_code=REASON_AI_CLI)
    return None


def _rule_listen(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    if context.listen_ports_by_pid.get(proc.pid):
        return CategoryDecision(category=Category.DEV_SERVER, reason_code=REASON_LISTEN)
    return None


def _rule_terminal_process(
    proc: RawProcess, context: CategorizationContext
) -> CategoryDecision | None:
    if _from_terminal(proc=proc, context=context):
        return CategoryDecision(category=Category.DEV_PROCESS, reason_code=REASON_TERMINAL_PROCESS)
    return None


Rule = Callable[[RawProcess, CategorizationContext], CategoryDecision | None]
# Evaluation order: the single source of truth for rules 1-9 (OTHER is the fallback).
RULES: tuple[Rule, ...] = (
    lambda proc, context: _early_decision(proc=proc, context=context),
    lambda proc, context: _app_decision(proc=proc, context=context),
    _rule_ai_cli,
    _rule_listen,
    _rule_terminal_process,
)


def categorize_process(proc: RawProcess, context: CategorizationContext) -> CategoryDecision:
    """Apply specification rules 1-9; excluded Docker processes have no category.

    Evaluation order: 1) SELF, 2) Docker scope exclusion, 3) SYSTEM, then
    SESSION, apps, AI_CLI, DEV_SERVER, DEV_PROCESS, OTHER. This deliberately
    swaps rules 2 and 3 of the literal specification: a Docker scope lives under
    ``system.slice``, outside ``user@<uid>.service``, so the SYSTEM rule would
    always catch it first and count its memory twice (System view and container
    group). Exclusion applies to any uid.

    Parameters
    ----------
    proc : RawProcess
        Process to classify, with a cgroup v2 path or its 0:: record.
    context : CategorizationContext
        Identity, ancestry, listening ports and additive protection configuration.
    """
    for rule in RULES:
        decision = rule(proc, context)
        if decision is not None:
            return decision
    return CategoryDecision(category=Category.OTHER, reason_code=REASON_OTHER)


def has_documents(
    appid: str | None, categories: Mapping[str, tuple[str, ...]], process_name: str
) -> bool:
    """Detect document apps using desktop metadata, falling back only if absent.

    Parameters
    ----------
    appid : str or None
        Desktop application identifier, if known.
    categories : Mapping[str, tuple[str, ...]]
        Desktop Categories by appid; an empty entry still means a desktop file exists.
    process_name : str
        Exact process name for the fallback when no desktop file is available.
    """
    if appid is not None and appid in categories:
        return any(category in DOCUMENT_DESKTOP_CATEGORIES for category in categories[appid])
    return process_name in DOCUMENT_APP_NAMES
