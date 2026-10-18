from collections.abc import Callable, Mapping

from wimm.model.enums import Category
from wimm.model.raw import RawProcess

from .categorize_tools import (
    CategorizationContext,
    CategoryDecision,
    ancestors,
    is_terminal,
    libpod_container_id,
    process_names,
    rule_ai_cli,
    rule_listen,
    rule_terminal_process,
    scope_decision,
)
from .cgroup_paths import components as _components
from .cgroup_paths import is_direct_user_service
from .cgroup_paths import matches as _matches
from .constants import (
    DBUS_NAME_PREFIX,
    DOCKER_SCOPE_PATTERNS,
    DOCUMENT_APP_NAMES,
    DOCUMENT_DESKTOP_CATEGORIES,
    PROTECTED_PROCESS_NAMES,
    REASON_ANCESTOR,
    REASON_EXCLUDED,
    REASON_OTHER,
    REASON_PODMAN_UNSEEN,
    REASON_PROTECTED_NAME,
    REASON_REMOTE_LOGIN,
    REASON_SELF,
    REASON_SESSION,
    REASON_SYSTEM,
    REASON_USER_SERVICE,
    SERVICE_SUFFIX,
    SESSION_SERVICE_PATTERNS,
    SESSION_SLICE,
    SHELL_NAMES,
    SYSTEMD_NAME,
    SYSTEMD_USER_FLAG,
    USER_UNIT_TEMPLATE,
    VTE_SCOPE_PATTERNS,
)
from .remote_sessions import in_remote_session, is_login_infrastructure

INHERITED_CATEGORIES = (Category.BROWSER, Category.DESKTOP_APP)

__all__ = [
    "CategorizationContext",
    "CategoryDecision",
    "categorize_process",
    "has_documents",
    "is_terminal_shell",
]


def _early_decision(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    parts = _components(proc=proc)
    if proc.pid == context.own_pid:
        return CategoryDecision(category=Category.SELF, reason_code=REASON_SELF)
    if any(_matches(name=part, patterns=DOCKER_SCOPE_PATTERNS) for part in parts):
        return CategoryDecision(category=None, reason_code=REASON_EXCLUDED)
    podman = _podman_decision(proc=proc, context=context)
    if podman is not None:
        return podman
    outside = _outside_user_manager(proc=proc, parts=parts, context=context)
    if outside is not None:
        return outside
    if _is_session(proc=proc):
        return CategoryDecision(category=Category.SESSION, reason_code=REASON_SESSION)
    if any(
        _matches(name=name, patterns=PROTECTED_PROCESS_NAMES + context.extra_protected_names)
        for name in process_names(proc=proc)
    ):
        return CategoryDecision(category=Category.SESSION, reason_code=REASON_PROTECTED_NAME)
    if is_direct_user_service(proc=proc) and not is_terminal(proc=proc):
        return CategoryDecision(category=Category.OTHER, reason_code=REASON_USER_SERVICE)
    return None


def _outside_user_manager(
    proc: RawProcess, parts: tuple[str, ...], context: CategorizationContext
) -> CategoryDecision | None:
    """Protect what is not the user's own, unless an opted-in SSH session process (R28)."""
    system = CategoryDecision(category=Category.SYSTEM, reason_code=REASON_SYSTEM)
    if proc.uid != context.own_uid:
        return system
    if USER_UNIT_TEMPLATE.format(uid=context.own_uid) in parts:
        return None
    if not (
        context.remote_sessions_actionable
        and in_remote_session(proc=proc, scopes=context.remote_scopes)
    ):
        return system
    if is_login_infrastructure(proc=proc, processes=context.processes):
        return CategoryDecision(category=Category.SYSTEM, reason_code=REASON_REMOTE_LOGIN)
    return None


def _podman_decision(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    """Podman scopes: the container's memory is counted by the engine, or else protected.

    Without the engine's view nothing counts that memory, so the process stays visible
    as protected SYSTEM: no action can reach a pid owned by a container.
    """
    container_id = libpod_container_id(proc=proc)
    if container_id is None:
        return None
    if container_id in context.engine_container_ids:
        return CategoryDecision(category=None, reason_code=REASON_EXCLUDED)
    return CategoryDecision(category=Category.SYSTEM, reason_code=REASON_PODMAN_UNSEEN)


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


def _app_decision(proc: RawProcess, context: CategorizationContext) -> CategoryDecision | None:
    direct = scope_decision(proc=proc)
    if direct is not None:
        return direct
    for ancestor in ancestors(proc=proc, context=context):
        if _early_decision(proc=ancestor, context=context) is not None:
            continue
        decision = scope_decision(proc=ancestor)
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


Rule = Callable[[RawProcess, CategorizationContext], CategoryDecision | None]
# Evaluation order: the single source of truth for rules 1-9 (OTHER is the fallback).
RULES: tuple[Rule, ...] = (
    lambda proc, context: _early_decision(proc=proc, context=context),
    lambda proc, context: _app_decision(proc=proc, context=context),
    rule_ai_cli,
    rule_listen,
    rule_terminal_process,
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
