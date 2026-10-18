"""R13, S18: the risk of cleaning a cache depends on its type, and an unlisted type is not safe."""

import pytest

from wimm.core.risk import RiskTarget, assess_risk, available_actions
from wimm.core.risk_table import CACHE_ASSESSMENTS
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, Risk
from wimm.model.snapshot import ActionOffer

K = CacheKind
# Written by hand on purpose: a new CacheKind is in neither set until someone classifies it.
RATED_SAFE: set[CacheKind] = {
    K.UV,
    K.NPM,
    K.PIP,
    K.THUMBNAILS,
    K.CARGO_REGISTRY,
    K.CARGO_GIT,
    K.GRADLE,
    K.GO_MOD,
    K.GO_BUILD,
    K.YARN,
    K.PNPM,
    K.BUN,
    K.CONDA,
    K.PLAYWRIGHT,
}
RATED_CAUTION: set[CacheKind] = {K.MAVEN, K.JETBRAINS, K.HUGGINGFACE, K.ANDROID_SDK}
# Q2=A: not downloadable again for sure (`ollama create`, an AVD with its data).
RATED_DANGER: set[CacheKind] = {K.OLLAMA, K.ANDROID_AVD}
NOT_A_CLEANABLE_CACHE: set[CacheKind] = {K.TRASH}  # emptied by TRASH_EMPTY, never by CACHE_CLEAN


def _assess(kind: CacheKind | None) -> tuple[Risk, tuple[str, ...]]:
    result = assess_risk(
        target=RiskTarget(kind="cache", cache_kind=kind), action=ActionKind.CACHE_CLEAN
    )
    return result.level, result.consequences


def test_every_cache_kind_is_classified_by_hand() -> None:
    listed = RATED_SAFE | RATED_CAUTION | RATED_DANGER | NOT_A_CLEANABLE_CACHE

    assert listed == set(CacheKind), "classify the new CacheKind here and in CACHE_ASSESSMENTS"


@pytest.mark.parametrize("kind", sorted(RATED_SAFE, key=repr))
def test_cache_risk_depends_on_kind_safe_types(kind: CacheKind) -> None:
    assert _assess(kind)[0] is Risk.SAFE


@pytest.mark.parametrize("kind", sorted(RATED_CAUTION, key=repr))
def test_cache_risk_depends_on_kind_caution_types(kind: CacheKind) -> None:
    level, consequences = _assess(kind)

    assert level is Risk.CAUTION
    assert len(consequences) == 1 and consequences[0]


def test_cache_risk_depends_on_kind() -> None:
    assert _assess(K.GRADLE)[0] is Risk.SAFE
    assert _assess(K.MAVEN)[0] is Risk.CAUTION
    assert _assess(K.JETBRAINS)[0] is Risk.CAUTION


def test_no_cache_kind_falls_on_safe_without_being_listed() -> None:
    for kind in CacheKind:
        if _assess(kind)[0] is Risk.SAFE:
            assert kind in RATED_SAFE, f"{kind} is rated SAFE without being listed"


def test_a_kind_missing_from_the_table_is_caution_beside_its_listed_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _assess(K.BUN)[0] is Risk.SAFE

    monkeypatch.delitem(CACHE_ASSESSMENTS, K.BUN)

    level, consequences = _assess(K.BUN)
    assert level is Risk.CAUTION
    assert consequences and consequences != _assess(K.UV)[1]


def test_the_trash_is_not_a_cache_clean_target() -> None:
    assert _assess(K.TRASH)[0] is Risk.CAUTION


def test_a_cache_without_a_kind_keeps_the_generic_rating() -> None:
    level, consequences = _assess(None)

    assert level is Risk.SAFE
    assert consequences == ("I pacchetti si riscaricano quando servono.",)


def test_consequences_name_what_the_user_loses_per_type() -> None:
    texts = {kind: _assess(kind)[1] for kind in (K.MAVEN, K.JETBRAINS, K.PLAYWRIGHT, K.GO_BUILD)}

    assert len(set(texts.values())) == 4
    assert "mvn install" in texts[K.MAVEN][0]
    assert "indic" in texts[K.JETBRAINS][0]


def test_offers_carry_the_risk_of_the_cache_type() -> None:
    maven = available_actions(target=RiskTarget(kind="cache", cache_kind=K.MAVEN))
    uv = available_actions(target=RiskTarget(kind="cache", cache_kind=K.UV))

    assert maven == (ActionOffer(kind=ActionKind.CACHE_CLEAN, risk=Risk.CAUTION),)
    assert uv == (ActionOffer(kind=ActionKind.CACHE_CLEAN, risk=Risk.SAFE),)


def test_model_cache_risk() -> None:
    """Q2=A: HuggingFace and the Android SDK come back; ollama models and AVDs may not."""
    levels = {kind: _assess(kind)[0] for kind in (*RATED_CAUTION, *RATED_DANGER)}

    assert levels[K.HUGGINGFACE] is Risk.CAUTION
    assert levels[K.ANDROID_SDK] is Risk.CAUTION
    assert levels[K.OLLAMA] is Risk.DANGER
    assert levels[K.ANDROID_AVD] is Risk.DANGER


@pytest.mark.parametrize("kind", sorted(RATED_DANGER, key=repr))
def test_danger_caches_carry_one_text_of_their_own(kind: CacheKind) -> None:
    level, consequences = _assess(kind)

    assert level is Risk.DANGER
    assert len(consequences) == 1 and consequences[0]


def test_model_cache_consequences_say_how_to_get_the_data_back() -> None:
    assert "GB" in _assess(K.HUGGINGFACE)[1][0]
    assert "ollama pull" in _assess(K.OLLAMA)[1][0]
    assert "sdkmanager" in _assess(K.ANDROID_SDK)[1][0]
    assert "non si recuper" in _assess(K.ANDROID_AVD)[1][0]
    kinds = (K.HUGGINGFACE, K.OLLAMA, K.ANDROID_AVD, K.ANDROID_SDK)
    assert len({_assess(k)[1] for k in kinds}) == 4


def test_offers_for_a_danger_cache_carry_danger() -> None:
    offer = available_actions(target=RiskTarget(kind="cache", cache_kind=K.OLLAMA))

    assert offer == (ActionOffer(kind=ActionKind.CACHE_CLEAN, risk=Risk.DANGER),)
