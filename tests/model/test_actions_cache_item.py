import pytest

from wimm.model import (
    ACTION_TARGET_SHAPES,
    ActionKind,
    ActionRequest,
    DirFingerprint,
    ItemBlob,
    ItemFingerprint,
    PlanStep,
    Risk,
    ServedModelFingerprint,
    TargetId,
    TargetShape,
)
from wimm.model.actions import ACTION_FINGERPRINT_TYPES

HUB = "/home/u/.cache/huggingface"


def _blob(*, path: str = "hub/blobs/3b/excl", size: int = 2000) -> ItemBlob:
    return ItemBlob(path=path, size=size, st_ino=77, st_dev=2049)


def _fingerprint(*, blobs: tuple[ItemBlob, ...] = ()) -> ItemFingerprint:
    return ItemFingerprint(realpath=f"{HUB}/hub/models--org--a", st_ino=5, st_dev=2049, blobs=blobs)


def test_cache_item_remove_targets_one_item_and_wants_an_item_fingerprint() -> None:
    assert ActionKind.CACHE_ITEM_REMOVE.value == "cache_item_remove"
    assert ACTION_TARGET_SHAPES[ActionKind.CACHE_ITEM_REMOVE] is TargetShape.TARGET
    assert ACTION_FINGERPRINT_TYPES[ActionKind.CACHE_ITEM_REMOVE] == (
        ItemFingerprint,
        ServedModelFingerprint,
    )


def test_request_needs_a_target_id() -> None:
    request = ActionRequest(
        kind=ActionKind.CACHE_ITEM_REMOVE, target_id=TargetId("huggingface:models--org--a")
    )
    assert request.target_id == "huggingface:models--org--a"
    with pytest.raises(ValueError):
        ActionRequest(kind=ActionKind.CACHE_ITEM_REMOVE)


def test_step_accepts_the_item_fingerprint_with_its_blobs() -> None:
    fingerprint = _fingerprint(blobs=(_blob(),))
    step = PlanStep(
        order=1,
        kind=ActionKind.CACHE_ITEM_REMOVE,
        target_label="org/a",
        fingerprint=fingerprint,
        risk=Risk.CAUTION,
    )
    assert step.fingerprint == fingerprint
    assert fingerprint.blobs[0].path == "hub/blobs/3b/excl"


def test_step_refuses_a_directory_fingerprint_for_the_item_kind() -> None:
    wrong = DirFingerprint(realpath=f"{HUB}/hub/models--org--a", st_ino=5, st_dev=2049)
    with pytest.raises(ValueError, match="fingerprint does not match"):
        PlanStep(
            order=1,
            kind=ActionKind.CACHE_ITEM_REMOVE,
            target_label="org/a",
            fingerprint=wrong,
            risk=Risk.CAUTION,
        )


def test_item_fingerprint_is_refused_for_a_cache_clean_step() -> None:
    with pytest.raises(ValueError, match="fingerprint does not match"):
        PlanStep(
            order=1,
            kind=ActionKind.CACHE_CLEAN,
            target_label="x",
            fingerprint=_fingerprint(),
            risk=Risk.SAFE,
        )


def test_blobs_must_be_a_tuple() -> None:
    with pytest.raises(ValueError, match="blobs"):
        ItemFingerprint(realpath="/a", st_ino=1, st_dev=1, blobs=[_blob()])  # type: ignore[arg-type]


def test_fingerprint_refuses_duplicate_blob_paths() -> None:
    with pytest.raises(ValueError, match="unique"):
        _fingerprint(blobs=(_blob(), _blob(size=1)))


@pytest.mark.parametrize("path", ["", "  ", "/abs/blob", "hub/../etc/x", "../x", "a//b"])
def test_blob_path_must_be_relative_without_parent_steps(path: str) -> None:
    with pytest.raises(ValueError):
        _blob(path=path)


def test_blob_size_must_not_be_negative() -> None:
    with pytest.raises(ValueError):
        _blob(size=-1)
    assert _blob(size=0).size == 0
