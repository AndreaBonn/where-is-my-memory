import pytest

from wimm.core.risk import RiskTarget
from wimm.model.enums import ActionKind, Risk
from wimm.ui.disk_model import ActionSpec, make_row

CONSEQUENCE = "I pacchetti si riscaricano quando servono."


def _cache_action(*, consequence: str = "") -> ActionSpec:
    return ActionSpec(
        kind=ActionKind.CACHE_CLEAN,
        target=RiskTarget(kind="cache"),
        target_id="uv",
        consequence=consequence,
    )


@pytest.mark.parametrize(
    ("target", "action_kind", "risk", "text"),
    [
        (RiskTarget(kind="cache"), ActionKind.CACHE_CLEAN, Risk.SAFE, "Sicuro"),
        (RiskTarget(kind="devdir"), ActionKind.DEVDIR_DELETE, Risk.CAUTION, "Attenzione"),
        (RiskTarget(kind="volume"), ActionKind.VOLUME_REMOVE, Risk.DANGER, "Pericolo"),
    ],
)
def test_make_row_badge_is_the_short_risk_text(
    target: RiskTarget, action_kind: ActionKind, risk: Risk, text: str
) -> None:
    action = ActionSpec(kind=action_kind, target=target, target_id="x", consequence=CONSEQUENCE)

    row = make_row(title="t", subtitle="s", size=1, action=action)

    assert (row.risk, row.risk_text) == (risk, text)


def test_make_row_carries_the_consequence_of_the_action() -> None:
    row = make_row(title="t", subtitle="s", size=1, action=_cache_action(consequence=CONSEQUENCE))

    assert row.consequence == CONSEQUENCE


def test_make_row_without_action_has_no_consequence_and_no_badge() -> None:
    row = make_row(title="t", subtitle="s", size=1, action=None)

    assert (row.consequence, row.risk_text) == ("", None)
