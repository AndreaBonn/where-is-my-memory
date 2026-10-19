"""Rows and sections of the Disco page, and how a row is built from a risk assessment."""

from dataclasses import dataclass

from wimm.core.risk import RiskTarget, assess_risk
from wimm.i18n import N_, _, decimal_separator
from wimm.model.enums import ActionKind, Risk
from wimm.ui.format import RISK_STYLE, RISK_TEXT, format_size

UNKNOWN_SIZE_TEXT = N_("dimensione sconosciuta")


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
    consequence: str = ""


@dataclass(frozen=True, slots=True)
class SectionActionView:
    """A mass action of a section (RF-22), with its button label."""

    kind: ActionKind
    label: str


@dataclass(frozen=True, slots=True)
class RootsState:
    """The saved project folders as the page needs them: the missing ones, and any usable."""

    missing: tuple[str, ...] = ()
    usable: bool = True


ROOTS_FINE = RootsState()


@dataclass(frozen=True, slots=True)
class EmptyStateView:
    """An empty state inside a section: headline, one plain sentence, the primary action."""

    title: str
    text: str
    action_label: str


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
    warnings: tuple[str, ...] = ()
    empty_state: EmptyStateView | None = None


def more_text(*, count: int) -> str | None:
    """The "e altre N" counter for rows a cap hid; None when nothing is hidden."""
    if count <= 0:
        return None
    # The thousands separator is the opposite of the decimal one in both languages.
    thousands = "." if decimal_separator() == "," else ","
    return _("e altre {count}").format(count=f"{count:,}".replace(",", thousands))


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """What a row can do: the risk target, the action, the id it acts on, what it costs.

    `consequence` is the `row_consequence` text, the same as the confirmation dialog's.
    """

    kind: ActionKind
    target: RiskTarget
    target_id: str | None
    consequence: str = ""


def make_row(
    *, title: str, subtitle: str, size: int | None, action: ActionSpec | None
) -> DiskRowView:
    """Build a row; the badge comes from the planner's own assessment, no action = no badge."""
    size_text = _(UNKNOWN_SIZE_TEXT) if size is None else format_size(size=size)
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
        risk_text=_(RISK_TEXT[level]),
        risk_style=RISK_STYLE[level],
        action_kind=action.kind,
        target_id=action.target_id,
        size_bytes=size or 0,
        consequence=action.consequence,
    )
