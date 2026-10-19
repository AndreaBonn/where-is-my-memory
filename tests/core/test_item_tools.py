"""Which item kinds can be removed now: Android items need their tool, AVDs their .ini."""

import pytest

from wimm.core.item_tools import is_item_removable, item_tool, withheld_item_kinds
from wimm.model.cache_items import CacheItem, ItemBlob
from wimm.model.disk import CacheKind
from wimm.model.enums import CacheItemKind

SDK = "/home/u/Android/Sdk"
SDK_TOOL = f"{SDK}/cmdline-tools/latest/bin/sdkmanager"


def _none(name: str) -> str | None:
    return None


@pytest.mark.parametrize("in_sdk", [True, False])
def test_item_tool_prefers_the_sdk_of_the_table_over_path(in_sdk: bool) -> None:
    tool = item_tool(
        kind=CacheKind.ANDROID_SDK,
        sdk_roots=(SDK,),
        is_executable=lambda path: in_sdk and path == SDK_TOOL,
        which=lambda name: f"/usr/bin/{name}",
    )
    assert tool == (SDK_TOOL if in_sdk else "/usr/bin/sdkmanager")


@pytest.mark.parametrize("found", [None, "bin/avdmanager", "/opt/avdmanager"])
def test_item_tool_takes_only_an_absolute_path_from_path(found: str | None) -> None:
    tool = item_tool(
        kind=CacheKind.ANDROID_AVD,
        sdk_roots=(),
        is_executable=lambda path: False,
        which=lambda name: found,
    )
    assert tool == ("/opt/avdmanager" if found == "/opt/avdmanager" else None)


def test_withheld_item_kinds_lists_the_kinds_without_a_tool() -> None:
    def is_executable(path: str) -> bool:
        return path == SDK_TOOL

    withheld = withheld_item_kinds(sdk_roots=(SDK,), is_executable=is_executable, which=_none)
    assert withheld == frozenset({CacheKind.ANDROID_AVD})
    everything = withheld_item_kinds(sdk_roots=(), is_executable=is_executable, which=_none)
    assert everything == frozenset({CacheKind.ANDROID_SDK, CacheKind.ANDROID_AVD})


def _avd(*, blobs: tuple[ItemBlob, ...]) -> CacheItem:
    return CacheItem(
        id="Pixel",
        title="Pixel",
        path="/home/u/.android/avd/Pixel.avd",
        size=10,
        st_ino=1,
        st_dev=2,
        kind=CacheItemKind.ANDROID_AVD,
        blobs=blobs,
    )


def test_an_avd_is_removable_only_with_its_ini() -> None:
    ini = ItemBlob(path="Pixel.ini", size=1, st_ino=3, st_dev=2)
    assert is_item_removable(item=_avd(blobs=(ini,)))
    assert not is_item_removable(item=_avd(blobs=()))
    package = CacheItem(
        id="platforms;android-34",
        title="platforms;android-34",
        path=f"{SDK}/platforms/android-34",
        size=1,
        st_ino=4,
        st_dev=2,
        kind=CacheItemKind.ANDROID_PACKAGE,
    )
    assert is_item_removable(item=package)
