"""Rows and sections of the Disco page, and how a row is built from a risk assessment."""

from dataclasses import dataclass

from wimm.core.risk import RiskTarget, assess_risk
from wimm.model.enums import ActionKind, Risk
from wimm.ui.format import DISK_RISK_CONSEQUENCE, RISK_STYLE, format_size

UNKNOWN_SIZE_TEXT = "dimensione sconosciuta"


@dataclass(frozen=True, slots=True)
class DiskRowView:
    """One row; `action_kind` and `target_id` let the page build the action request later."""

    title: str
    subtitle: str
    size_text: str
    risk: Risk | None = None
    risk_text: str | None = None
    risk_style: str | None = None
    action_kind: ActionKind | None = None
    target_id: str | None = None
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class SectionActionView:
    """A mass action of a section (RF-22), with its button label."""

    kind: ActionKind
    label: str


@dataclass(frozen=True, slots=True)
class DiskSectionView:
    key: str
    title: str
    rows: tuple[DiskRowView, ...] = ()
    more_text: str | None = None
    message: str | None = None
    actions: tuple[SectionActionView, ...] = ()
    description: str = ""
    tier: str = ""


def more_text(*, count: int) -> str | None:
    """The "e altre N" counter for rows a cap hid; None when nothing is hidden."""
    if count <= 0:
        return None
    return "e altre " + f"{count:,}".replace(",", ".")


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """What a row can do: the planner's risk target, the action and the id it acts on."""

    kind: ActionKind
    target: RiskTarget
    target_id: str | None


def make_row(
    *, title: str, subtitle: str, size: int | None, action: ActionSpec | None
) -> DiskRowView:
    """Build a row; the badge comes from the planner's own assessment, no action = no badge."""
    size_text = UNKNOWN_SIZE_TEXT if size is None else format_size(size=size)
    if action is None:
        return DiskRowView(
            title=title, subtitle=subtitle, size_text=size_text, size_bytes=size or 0
        )
    level: Risk = assess_risk(target=action.target, action=action.kind).level
    return DiskRowView(
        title=title,
        subtitle=subtitle,
        size_text=size_text,
        risk=level,
        risk_text=DISK_RISK_CONSEQUENCE[level],
        risk_style=RISK_STYLE[level],
        action_kind=action.kind,
        target_id=action.target_id,
        size_bytes=size or 0,
    )
