"""Android item rows: offered only with their tool, a device only with its .ini (C-L4-1/2)."""

import pytest

from tests.core.disk_helpers import MB, report
from wimm.model.cache_items import CacheItem, ItemBlob
from wimm.model.disk import CacheEntry, CacheKind
from wimm.model.enums import ActionKind, CacheItemKind
from wimm.ui.disk_items import item_rows
from wimm.ui.disk_model import DiskRowView
from wimm.ui.disk_view import build_disk_sections, withheld_for_report

SDK = "/home/u/Android/Sdk"
AVD_HOME = "/home/u/.android/avd"
INI = ItemBlob(path="Pixel.ini", size=1, st_ino=8, st_dev=2049)


def _sdk_entry() -> CacheEntry:
    package = CacheItem(
        id="platforms;android-34",
        title="platforms;android-34",
        path=f"{SDK}/platforms/android-34",
        size=MB,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.ANDROID_PACKAGE,
    )
    return CacheEntry(
        kind=CacheKind.ANDROID_SDK, path=SDK, size=MB, st_ino=4, st_dev=2049, items=(package,)
    )


def _avd_entry(*, blobs: tuple[ItemBlob, ...]) -> CacheEntry:
    device = CacheItem(
        id="Pixel",
        title="Pixel",
        path=f"{AVD_HOME}/Pixel.avd",
        size=MB,
        st_ino=6,
        st_dev=2049,
        kind=CacheItemKind.ANDROID_AVD,
        blobs=blobs,
    )
    return CacheEntry(
        kind=CacheKind.ANDROID_AVD, path=AVD_HOME, size=MB, st_ino=7, st_dev=2049, items=(device,)
    )


@pytest.mark.parametrize("removable", [True, False])
def test_item_rows_offer_removal_only_when_the_tool_is_there(removable: bool) -> None:
    (row,) = item_rows(entry=_sdk_entry(), removable=removable).rows
    assert (row.action_kind is not None) is removable
    if removable:
        assert row.action_kind is ActionKind.CACHE_ITEM_REMOVE


@pytest.mark.parametrize("with_ini", [True, False])
def test_a_device_without_its_ini_is_shown_but_not_offered(with_ini: bool) -> None:
    (row,) = item_rows(entry=_avd_entry(blobs=(INI,) if with_ini else ())).rows
    assert row.title == "Pixel"
    assert (row.action_kind is not None) is with_ini


def _sdk_row(*, withheld: frozenset[CacheKind]) -> DiskRowView:
    sections = build_disk_sections(
        report=report(caches=(_sdk_entry(),)), min_age_days=30, withheld=withheld
    )
    rows = [row for section in sections for row in section.rows if row.subtitle == SDK]
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize("missing", [True, False])
def test_a_missing_sdkmanager_withholds_the_items_and_keeps_the_cache_action(
    missing: bool,
) -> None:
    row = _sdk_row(withheld=frozenset({CacheKind.ANDROID_SDK}) if missing else frozenset())
    assert row.action_kind is ActionKind.CACHE_CLEAN
    (item,) = row.items
    assert (item.action_kind is None) is missing


@pytest.mark.parametrize("in_sdk", [True, False])
def test_withheld_kinds_find_sdkmanager_in_the_reported_sdk(in_sdk: bool) -> None:
    tool = f"{SDK}/cmdline-tools/latest/bin/sdkmanager"
    withheld = withheld_for_report(
        report=report(caches=(_sdk_entry(),)),
        which=lambda name: None,
        is_executable=lambda path: in_sdk and path == tool,
    )
    assert (CacheKind.ANDROID_SDK in withheld) is not in_sdk
    assert CacheKind.ANDROID_AVD in withheld
    assert CacheKind.GO_MOD in withheld
