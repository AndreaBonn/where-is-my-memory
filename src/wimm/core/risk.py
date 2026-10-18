from dataclasses import dataclass
from typing import Literal

from wimm.core.constants import DB_PROCESS_NAMES
from wimm.core.risk_table import (
    CACHE_ASSESSMENTS,
    CONSEQUENCES,
    STATIC_ASSESSMENTS,
    UNLISTED_CACHE_ASSESSMENT,
    ConsequenceKey,
)
from wimm.i18n import _
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, ActivityState, Category, Protection, Risk, protection_of
from wimm.model.snapshot import ActionOffer

TargetKind = Literal[
    "process",
    "desktop_app",
    "browser",
    "terminal",
    "container",
    "compose_project",
    "image",
    "build_cache",
    "volume",
    "cache",
    "trash",
    "devdir",
]
PROCESS_KINDS = ("process", "desktop_app", "browser", "terminal")
DEVELOPMENT_CATEGORIES = (Category.DEV_SERVER, Category.DEV_PROCESS)

ACTIONS_BY_KIND: dict[TargetKind, tuple[ActionKind, ...]] = {
    "process": (ActionKind.PROCESS_TERMINATE,),
    "desktop_app": (ActionKind.APP_CLOSE,),
    "browser": (ActionKind.APP_CLOSE,),
    "terminal": (ActionKind.APP_CLOSE,),
    "compose_project": (
        ActionKind.GROUP_STOP,
        ActionKind.COMPOSE_DOWN,
        ActionKind.COMPOSE_DOWN_VOLUMES,
    ),
    "image": (ActionKind.IMAGE_REMOVE,),
    "build_cache": (ActionKind.BUILDER_PRUNE,),
    "volume": (ActionKind.VOLUME_REMOVE,),
    "cache": (ActionKind.CACHE_CLEAN,),
    "trash": (ActionKind.TRASH_EMPTY,),
    "devdir": (ActionKind.DEVDIR_DELETE,),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskTarget:
    """Pure target facts; document and shell flags come from categorization."""

    kind: TargetKind
    category: Category = Category.OTHER
    activity: ActivityState = ActivityState.UNKNOWN
    is_foreground_on_tty: bool = False
    has_documents: bool = False
    is_terminal_shell: bool = False
    process_name: str = ""
    cwd: str | None = None
    has_repo_digests: bool | None = None
    dangling: bool | None = None
    is_running: bool | None = None
    volume_names: tuple[str, ...] = ()
    cache_kind: CacheKind | None = None

    def __post_init__(self) -> None:
        if self.kind == "container" and self.is_running is None:
            raise ValueError("is_running is required for container targets")
        if self.kind == "image":
            if self.has_repo_digests is None:
                raise ValueError("has_repo_digests is required for image targets")
            if self.dangling is None:
                raise ValueError("dangling is required for image targets")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: Risk
    consequences: tuple[str, ...]


def _assessment(level: Risk, key: ConsequenceKey) -> RiskAssessment:
    return RiskAssessment(level=level, consequences=(_(CONSEQUENCES[key]),))


def _app_assessment(target: RiskTarget) -> RiskAssessment:
    if target.has_documents:
        key = ConsequenceKey.DOCUMENTS
    elif target.kind == "browser" or target.category is Category.BROWSER:
        key = ConsequenceKey.BROWSER
    elif target.kind == "terminal" or target.category is Category.TERMINAL:
        key = ConsequenceKey.TERMINAL
    elif target.category is Category.OTHER and target.kind == "process":
        key = ConsequenceKey.OTHER
    else:
        key = ConsequenceKey.APP
    return _assessment(level=Risk.CAUTION, key=key)


def _process_assessment(target: RiskTarget, action: ActionKind) -> RiskAssessment:
    if action is ActionKind.PROCESS_KILL:
        dangerous = target.has_documents or target.process_name in DB_PROCESS_NAMES
        return _assessment(
            level=Risk.DANGER if dangerous else Risk.CAUTION, key=ConsequenceKey.KILL
        )
    result = _process_category_assessment(target=target)
    if target.is_foreground_on_tty:
        return RiskAssessment(
            level=max(Risk.CAUTION, result.level),
            consequences=(_(CONSEQUENCES[ConsequenceKey.FOREGROUND]), *result.consequences),
        )
    return result


def _process_category_assessment(target: RiskTarget) -> RiskAssessment:
    if target.has_documents or target.kind in ("desktop_app", "browser", "terminal"):
        return _app_assessment(target=target)
    if target.category is Category.AI_CLI:
        return _assessment(level=Risk.CAUTION, key=ConsequenceKey.AGENT)
    if target.category not in DEVELOPMENT_CATEGORIES:
        return _app_assessment(target=target)
    if target.activity is not ActivityState.IDLE:
        return _assessment(level=Risk.CAUTION, key=ConsequenceKey.ACTIVE)
    # How to restart it is the dialog's "Per riaccenderlo" line (C3), not a consequence.
    return _assessment(level=Risk.SAFE, key=ConsequenceKey.IDLE)


def _applicable_actions(target: RiskTarget) -> tuple[ActionKind, ...]:
    if target.kind == "container":
        action = ActionKind.CONTAINER_STOP if target.is_running else ActionKind.CONTAINER_REMOVE
        return (action,)
    return ACTIONS_BY_KIND[target.kind]


def assess_risk(target: RiskTarget, action: ActionKind) -> RiskAssessment:
    """Assess an applicable target/action pair without I/O.

    Parameters
    ----------
    target : RiskTarget
        Categorized facts; images are unused and volumes orphaned.
    action : ActionKind
        Requested action, including explicit force closure.

    Returns
    -------
    RiskAssessment
        Severity and Italian consequences from specification 5.3.

    Raises
    ------
    ValueError
        If the action does not apply to this target and state.
    """
    is_kill = action is ActionKind.PROCESS_KILL and target.kind in PROCESS_KINDS
    if not is_kill and action not in _applicable_actions(target=target):
        raise ValueError(f"Action {action.value} is not applicable to {target.kind}")
    if target.kind in PROCESS_KINDS:
        return _process_assessment(target=target, action=action)
    return _resource_assessment(target=target, action=action)


def _resource_assessment(target: RiskTarget, action: ActionKind) -> RiskAssessment:
    if action is ActionKind.COMPOSE_DOWN_VOLUMES:
        volumes = ", ".join(target.volume_names) or _("associati al progetto")
        return RiskAssessment(
            level=Risk.DANGER,
            consequences=(_(CONSEQUENCES[ConsequenceKey.DOWN_VOLUMES]).format(volumes=volumes),),
        )
    if action is ActionKind.IMAGE_REMOVE:
        if target.dangling:
            return RiskAssessment(level=Risk.SAFE, consequences=())
        if target.has_repo_digests:
            return _assessment(level=Risk.SAFE, key=ConsequenceKey.REGISTRY)
        return _assessment(level=Risk.CAUTION, key=ConsequenceKey.LOCAL_IMAGE)
    if action is ActionKind.CONTAINER_STOP:
        return RiskAssessment(
            level=Risk.SAFE,
            consequences=(
                _(CONSEQUENCES[ConsequenceKey.STOP]),
                _(CONSEQUENCES[ConsequenceKey.STOP_TIMEOUT]),
            ),
        )
    if action is ActionKind.CACHE_CLEAN and target.cache_kind is not None:
        level, key = CACHE_ASSESSMENTS.get(target.cache_kind, UNLISTED_CACHE_ASSESSMENT)
        return _assessment(level=level, key=key)
    level, key = STATIC_ASSESSMENTS[action]
    return _assessment(level=level, key=key)


def available_actions(target: RiskTarget) -> tuple[ActionOffer, ...]:
    """Offer initial actions, excluding protected targets and terminal shells.

    Parameters
    ----------
    target : RiskTarget
        Facts for a process, app or eligible resource.

    Returns
    -------
    tuple[ActionOffer, ...]
        Applicable actions with assessed risk; never force closure.
    """
    if protection_of(category=target.category) is Protection.PROTECTED or target.is_terminal_shell:
        return ()
    return tuple(
        ActionOffer(kind=action, risk=assess_risk(target=target, action=action).level)
        for action in _applicable_actions(target=target)
    )


def group_primary_action(
    member_offers: tuple[ActionOffer, ...], group_kind: Category
) -> ActionOffer | None:
    """Aggregate selected member offers using their maximum severity.

    Parameters
    ----------
    member_offers : tuple[ActionOffer, ...]
        One selected action per actionable member.
    group_kind : Category
        Group category; PROJECT always uses aggregate stop.

    Returns
    -------
    ActionOffer or None
        Aggregate stop for multiple members, otherwise the single offer.
    """
    if not member_offers:
        return None
    kind = ActionKind.GROUP_STOP
    if len(member_offers) == 1 and group_kind is not Category.PROJECT:
        kind = member_offers[0].kind
    return ActionOffer(kind=kind, risk=max(offer.risk for offer in member_offers))
