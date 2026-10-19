import pytest

from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.row_consequence import row_consequence
from wimm.model import (
    CacheEntry,
    CacheItem,
    CacheItemKind,
    CacheKind,
    DiskReport,
    ItemBlob,
    ItemFingerprint,
)
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest

from .disk_helpers import MB, report
from .planning_disk_helpers import _plan

HUB = "/home/u/.cache/huggingface"
BLOB = ItemBlob(path="hub/blobs/3b/excl", size=2 * MB, st_ino=77, st_dev=2049)


def _item(*, id: str = "models--org--a", kind: CacheItemKind = CacheItemKind.HF_MODEL) -> CacheItem:
    return CacheItem(
        id=id,
        title="org/a",
        path=f"{HUB}/hub/{id}",
        size=3 * MB,
        st_ino=5,
        st_dev=2049,
        kind=kind,
        blobs=(BLOB,),
    )


def _report(*, items: tuple[CacheItem, ...] = (_item(),)) -> DiskReport:
    entry = CacheEntry(
        kind=CacheKind.HUGGINGFACE, path=HUB, size=5 * MB, st_ino=11, st_dev=2049, items=items
    )
    return report(caches=(entry,))


def _remove(*, target: str, disk: DiskReport | None = None) -> Plan:
    return _plan(kind=ActionKind.CACHE_ITEM_REMOVE, disk=disk or _report(), target=target)


def test_plan_has_one_step_whose_fingerprint_carries_the_exclusive_blobs() -> None:
    plan = _remove(target="huggingface:models--org--a")

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.kind is ActionKind.CACHE_ITEM_REMOVE
    assert step.target_label == "org/a"
    assert step.fingerprint == ItemFingerprint(
        realpath=f"{HUB}/hub/models--org--a", st_ino=5, st_dev=2049, blobs=(BLOB,)
    )
    assert plan.estimated_reclaim_disk == 3 * MB


def test_a_huggingface_item_is_caution_and_needs_no_typed_phrase() -> None:
    plan = _remove(target="huggingface:models--org--a")
    assert plan.steps[0].risk is Risk.CAUTION
    assert plan.confirm_phrase is None


def test_consequence_says_redownload_and_exclusive_store_files() -> None:
    plan = _remove(target="huggingface:models--org--a")
    text = plan.consequences[0]
    assert "riscarica" in text
    assert "magazzino" in text
    assert plan.consequences == (
        row_consequence(
            action=ActionKind.CACHE_ITEM_REMOVE,
            target=RiskTarget(kind="cache_item", item_kind=CacheItemKind.HF_MODEL),
        ),
    )


def test_dataset_item_is_caution_with_its_own_text() -> None:
    disk = _report(items=(_item(id="datasets--org--d", kind=CacheItemKind.HF_DATASET),))
    plan = _remove(target="huggingface:datasets--org--d", disk=disk)
    assert plan.steps[0].risk is Risk.CAUTION
    assert plan.consequences[0] != _remove(target="huggingface:models--org--a").consequences[0]


@pytest.mark.parametrize(
    "target",
    [
        "huggingface:models--org--missing",
        "uv:models--org--a",
        "nosuchcache:models--org--a",
        "models--org--a",
        "huggingface:",
        ":models--org--a",
    ],
)
def test_unknown_or_malformed_target_is_an_invalid_request(target: str) -> None:
    with pytest.raises(InvalidRequest):
        _remove(target=target)


def test_without_a_report_the_item_cannot_be_planned() -> None:
    with pytest.raises(InvalidRequest):
        _plan(kind=ActionKind.CACHE_ITEM_REMOVE, disk=None, target="huggingface:models--org--a")


def test_an_item_of_unknown_kind_is_never_safe() -> None:
    result = assess_risk(target=RiskTarget(kind="cache_item"), action=ActionKind.CACHE_ITEM_REMOVE)
    assert result.level is Risk.CAUTION
