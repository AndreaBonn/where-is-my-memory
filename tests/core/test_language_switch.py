import pytest

from wimm.core import text
from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.sizes import format_size
from wimm.model.enums import ActionKind, ActivityState, Category

SERVER = RiskTarget(kind="process", category=Category.DEV_SERVER, activity=ActivityState.IDLE)


def snapshot_texts() -> tuple[object, ...]:
    risk = assess_risk(target=SERVER, action=ActionKind.PROCESS_TERMINATE)
    return (
        risk.consequences,
        text.reason_observing(elapsed_s=300),
        text.spoken_duration(seconds=3600),
        format_size(size=1_100_000_000),
    )


def test_core_texts_follow_a_language_change_in_the_same_process(
    request: pytest.FixtureRequest,
) -> None:
    # A text frozen at import time passes every single-language test: only a switch shows it.
    italian = snapshot_texts()
    request.getfixturevalue("english")

    assert italian == (
        ("Il server si ferma.",),
        "in osservazione da 5 minuti",
        "1 ora",
        "1,1 GB",
    )
    assert snapshot_texts() == (
        ("The server stops.",),
        "observing for 5 minutes",
        "1 hour",
        "1.1 GB",
    )
