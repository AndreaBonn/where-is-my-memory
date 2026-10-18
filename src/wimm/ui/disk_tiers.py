"""F4: every row of the Disco page sits in the tier of its own risk.

A section belongs to one tier, but two sections hold rows of several risks: the caches
(Maven costs a long download, ollama models hold data) and the images (a pulled one is
safe, one built here is not). Their odd rows move to a section of the right tier.
"""

from collections.abc import Iterable
from dataclasses import replace

from wimm.i18n import N_, _
from wimm.model.enums import ActionKind, Risk
from wimm.ui.disk_model import DiskRowView, DiskSectionView

# Source section -> {risk of the rows that move: (section that takes them, its title)}.
MOVES: dict[str, dict[Risk, tuple[str, str]]] = {
    "caches": {
        Risk.CAUTION: ("caches_review", N_("Cache pesanti da riscaricare")),
        Risk.DANGER: ("caches_data", N_("Modelli ed emulatori")),
    },
    "images": {Risk.SAFE: ("images_safe", N_("Immagini Docker scaricate"))},
}
# Mass actions whose every target is safe: they go with the safe rows wherever those go.
ALWAYS_SAFE_ACTIONS = frozenset({ActionKind.IMAGES_PRUNE_DANGLING})


def _moving_risk(*, row: DiskRowView, moves: dict[Risk, tuple[str, str]]) -> Risk | None:
    """The risk under which ``row`` leaves its section; None when it stays."""
    if row.action_kind is None or row.risk not in moves:
        return None
    return row.risk


def _split(section: DiskSectionView) -> list[DiskSectionView]:
    moves = MOVES[section.key]
    risks = [_moving_risk(row=row, moves=moves) for row in section.rows]
    if all(risk is None for risk in risks):
        return [section]
    kept = tuple(row for row, risk in zip(section.rows, risks, strict=True) if risk is None)
    moved = [
        DiskSectionView(key=key, title=_(title), rows=rows)
        for risk, (key, title) in moves.items()
        if (rows := tuple(r for r, m in zip(section.rows, risks, strict=True) if m is risk))
    ]
    # A mass action stays where actionable rows stay, else it follows the moved rows.
    acting = any(row.action_kind is not None for row in kept)
    own = tuple(a for a in section.actions if acting and a.kind not in ALWAYS_SAFE_ACTIONS)
    moved[0] = replace(moved[0], actions=tuple(a for a in section.actions if a not in own))
    if kept or own:
        return [replace(section, rows=kept, actions=own), *moved]
    # The source disappears: its "e altre N" counter goes with the rows that moved.
    moved[0] = replace(moved[0], more_text=section.more_text)
    return moved


def split_by_risk(*, sections: Iterable[DiskSectionView]) -> tuple[DiskSectionView, ...]:
    """The sections with every mixed one split so each row matches its tier."""
    result: list[DiskSectionView] = []
    for section in sections:
        result += _split(section) if section.key in MOVES else [section]
    return tuple(result)
