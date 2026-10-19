from dataclasses import replace

import pytest

from wimm.model import CacheEntry, CacheItem, CacheKind, DiskReport
from wimm.model.actions import ItemFingerprint, Plan
from wimm.model.cache_items import ItemBlob
from wimm.model.enums import ActionKind, CacheItemKind, Risk
from wimm.model.errors import InvalidRequest

from .disk_helpers import MB, report
from .planning_disk_helpers import _plan

ROOT = "/home/u/.cache"
AVD = CacheItemKind.ANDROID_AVD


def _entry(*, kind: CacheKind, folder: str, id: str, item_kind: CacheItemKind) -> CacheEntry:
    item = CacheItem(
        id=id,
        title=id,
        path=f"{ROOT}/{folder}/{id}",
        size=4 * MB,
        st_ino=9,
        st_dev=2049,
        kind=item_kind,
    )
    return CacheEntry(
        kind=kind, path=f"{ROOT}/{folder}", size=5 * MB, st_ino=3, st_dev=2049, items=(item,)
    )


def _remove(*, entry: CacheEntry) -> Plan:
    disk: DiskReport = report(caches=(entry,))
    target = f"{entry.kind.value}:{entry.items[0].id}"
    return _plan(kind=ActionKind.CACHE_ITEM_REMOVE, disk=disk, target=target)


def test_a_playwright_browser_plans_one_safe_step_with_no_blobs() -> None:
    entry = _entry(
        kind=CacheKind.PLAYWRIGHT,
        folder="ms-playwright",
        id="chromium-1181",
        item_kind=CacheItemKind.PLAYWRIGHT_BROWSER,
    )

    plan = _remove(entry=entry)

    assert len(plan.steps) == 1
    assert plan.steps[0].risk is Risk.SAFE
    assert plan.steps[0].fingerprint == ItemFingerprint(
        realpath=f"{ROOT}/ms-playwright/chromium-1181", st_ino=9, st_dev=2049, blobs=()
    )
    assert plan.estimated_reclaim_disk == 4 * MB


def test_a_jetbrains_product_plans_one_caution_step_with_no_blobs() -> None:
    entry = _entry(
        kind=CacheKind.JETBRAINS,
        folder="JetBrains",
        id="PyCharm2025.1",
        item_kind=CacheItemKind.JETBRAINS_PRODUCT,
    )

    plan = _remove(entry=entry)

    assert plan.steps[0].risk is Risk.CAUTION
    assert plan.steps[0].fingerprint == ItemFingerprint(
        realpath=f"{ROOT}/JetBrains/PyCharm2025.1", st_ino=9, st_dev=2049, blobs=()
    )


@pytest.mark.parametrize("with_ini", [True, False])
def test_an_avd_without_its_ini_is_refused_by_the_planner(with_ini: bool) -> None:
    entry = _entry(kind=CacheKind.ANDROID_AVD, folder="avd", id="Pixel", item_kind=AVD)
    ini = ItemBlob(path="Pixel.ini", size=10, st_ino=12, st_dev=2049)
    item = replace(entry.items[0], blobs=(ini,) if with_ini else ())
    entry = replace(entry, items=(item,))
    if with_ini:
        assert _remove(entry=entry).steps[0].risk is Risk.DANGER
    else:
        with pytest.raises(InvalidRequest, match="ini"):
            _remove(entry=entry)
