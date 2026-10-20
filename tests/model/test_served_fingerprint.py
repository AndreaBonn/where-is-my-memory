"""T-6.38a: the identity of a model served by the system ollama (design note section 2)."""

from typing import Any

import pytest

from wimm.model import ActionKind, DirFingerprint, ItemFingerprint, PlanStep, Risk
from wimm.model.actions import ACTION_FINGERPRINT_TYPES
from wimm.model.served_fingerprint import ServedModelFingerprint

MODEL_ID = "a2af6cc3eb7f"


def _step(*, kind: ActionKind, fingerprint: ServedModelFingerprint) -> PlanStep:
    return PlanStep(
        order=1, kind=kind, target_label="gemma3:4b", fingerprint=fingerprint, risk=Risk.DANGER
    )


def test_it_keeps_the_name_and_the_twelve_hex_id() -> None:
    fingerprint = ServedModelFingerprint(name="library/gemma3:4b", model_id=MODEL_ID)
    assert (fingerprint.name, fingerprint.model_id) == ("library/gemma3:4b", MODEL_ID)


@pytest.mark.parametrize("name", ["-rf:x", "", "gemma3", "a b:c", "x:\x1b[2K", "a/../b:c", 5])
def test_a_name_that_could_not_reach_an_argv_is_refused(name: Any) -> None:
    with pytest.raises(ValueError):
        ServedModelFingerprint(name=name, model_id=MODEL_ID)


@pytest.mark.parametrize(
    "model_id", ["", "a2af6cc3eb7", "A2AF6CC3EB7F", "a2af6cc3eb7f0", "zzzzzzzzzzzz"]
)
def test_an_id_that_is_not_twelve_lowercase_hex_is_refused(model_id: str) -> None:
    with pytest.raises(ValueError):
        ServedModelFingerprint(name="gemma3:4b", model_id=model_id)


def test_the_item_remove_step_accepts_it_next_to_the_folder_fingerprint() -> None:
    types = ACTION_FINGERPRINT_TYPES[ActionKind.CACHE_ITEM_REMOVE]
    assert types == (ItemFingerprint, ServedModelFingerprint)
    fingerprint = ServedModelFingerprint(name="gemma3:4b", model_id=MODEL_ID)
    assert _step(kind=ActionKind.CACHE_ITEM_REMOVE, fingerprint=fingerprint).fingerprint == (
        fingerprint
    )


@pytest.mark.parametrize("kind", [ActionKind.CACHE_CLEAN, ActionKind.DEVDIR_DELETE])
def test_no_other_action_accepts_it(kind: ActionKind) -> None:
    assert ACTION_FINGERPRINT_TYPES[kind] == (DirFingerprint,)
    with pytest.raises(ValueError):
        _step(kind=kind, fingerprint=ServedModelFingerprint(name="gemma3:4b", model_id=MODEL_ID))
