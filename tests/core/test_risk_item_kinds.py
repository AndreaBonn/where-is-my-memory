import pytest

from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.risk_table import ITEM_ASSESSMENTS
from wimm.model.enums import ActionKind, CacheItemKind, Risk

EXPECTED = {
    CacheItemKind.ANDROID_PACKAGE: (Risk.CAUTION, "sdkmanager"),
    CacheItemKind.ANDROID_AVD: (Risk.DANGER, "dispositivo virtuale"),
    CacheItemKind.PLAYWRIGHT_BROWSER: (Risk.SAFE, "playwright install"),
    CacheItemKind.JETBRAINS_PRODUCT: (Risk.CAUTION, "IDE"),
}


@pytest.mark.parametrize("kind", list(EXPECTED))
def test_item_kind_has_its_risk_and_a_plain_consequence(kind: CacheItemKind) -> None:
    level, phrase = EXPECTED[kind]
    result = assess_risk(
        target=RiskTarget(kind="cache_item", item_kind=kind), action=ActionKind.CACHE_ITEM_REMOVE
    )
    assert result.level is level
    assert phrase in result.consequences[0]
    assert "non classificato" not in result.consequences[0]


def test_every_item_kind_is_classified() -> None:
    assert set(ITEM_ASSESSMENTS) == set(CacheItemKind)
