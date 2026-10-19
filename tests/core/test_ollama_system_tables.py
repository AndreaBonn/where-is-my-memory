"""T-6.37a: the system store in the tables that hold one row per CacheKind."""

import pytest

from wimm.core.cache_specs import CACHE_SPECS
from wimm.core.cache_titles import CACHE_TITLES
from wimm.core.item_tools import ITEM_ONLY_KINDS
from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.risk_table import CACHE_ASSESSMENTS, ITEM_ASSESSMENTS, ConsequenceKey
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, CacheItemKind, Risk


def test_item_only_kinds_are_exactly_the_system_store() -> None:
    assert frozenset({CacheKind.OLLAMA_SYSTEM}) == ITEM_ONLY_KINDS


def test_the_home_ollama_store_is_not_item_only() -> None:
    assert CacheKind.OLLAMA not in ITEM_ONLY_KINDS


def test_system_store_has_a_title_of_its_own() -> None:
    title = CACHE_TITLES[CacheKind.OLLAMA_SYSTEM]

    assert title.strip()
    assert title != CACHE_TITLES[CacheKind.OLLAMA]


def test_every_kind_has_a_title() -> None:
    assert set(CACHE_TITLES) == set(CacheKind)


def test_system_store_has_no_folder_spec() -> None:
    kinds = {spec.kind for spec in CACHE_SPECS}

    assert CacheKind.OLLAMA_SYSTEM not in kinds
    assert kinds | ITEM_ONLY_KINDS == set(CacheKind)


def test_system_store_has_no_whole_cache_rating() -> None:
    assert CacheKind.OLLAMA_SYSTEM not in CACHE_ASSESSMENTS
    assert CacheKind.OLLAMA in CACHE_ASSESSMENTS


def test_a_whole_cache_clean_of_the_system_store_is_never_rated_safe() -> None:
    target = RiskTarget(kind="cache", cache_kind=CacheKind.OLLAMA_SYSTEM)

    assert assess_risk(target=target, action=ActionKind.CACHE_CLEAN).level is not Risk.SAFE


def test_a_system_model_is_danger_with_the_ollama_item_consequence() -> None:
    assert ITEM_ASSESSMENTS[CacheItemKind.OLLAMA_MODEL] == (Risk.DANGER, ConsequenceKey.ITEM_OLLAMA)
    target = RiskTarget(kind="cache_item", item_kind=CacheItemKind.OLLAMA_MODEL)

    result = assess_risk(target=target, action=ActionKind.CACHE_ITEM_REMOVE)

    assert result.level is Risk.DANGER
    assert "ollama pull" in result.consequences[0]


@pytest.mark.parametrize("kind", [k for k in CacheKind if k not in ITEM_ONLY_KINDS])
def test_every_other_kind_keeps_its_spec(kind: CacheKind) -> None:
    assert kind in {spec.kind for spec in CACHE_SPECS}
