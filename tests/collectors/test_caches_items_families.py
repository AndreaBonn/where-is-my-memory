import os
from pathlib import Path

from wimm.collectors.cache_table import read_cache_table
from wimm.collectors.caches import collect_caches
from wimm.model.disk import CacheEntry, CacheKind


def _write(path: Path, payload: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * payload)


def _collect(home: Path, tmp_path: Path) -> dict[CacheKind, CacheEntry]:
    table = read_cache_table(environ={}, home=home, roots=())
    found = collect_caches(table=table, cache_dir=tmp_path / "sizes", sleep=lambda _s: None)
    return {entry.kind: entry for entry in found}


def _size(path: Path) -> int:
    return os.lstat(path).st_blocks * 512


def _accounted(entry: CacheEntry) -> int:
    return sum(i.size for i in entry.items) + entry.rest.shared + entry.rest.unattributed


def test_collect_caches_splits_the_android_sdk_into_packages(tmp_path: Path) -> None:
    sdk = tmp_path / "home" / "Android" / "Sdk"
    _write(sdk / "platforms" / "android-35" / "package.xml", 100)
    _write(sdk / "platforms" / "android-35" / "android.jar", 20000)
    _write(sdk / "licenses" / "android-sdk-license", 40)
    _write(sdk / "cmdline-tools" / "latest" / "package.xml", 100)
    entry = _collect(tmp_path / "home", tmp_path)[CacheKind.ANDROID_SDK]
    (item,) = entry.items
    assert item.id == "platforms;android-35"
    assert item.size == _size(sdk / "platforms/android-35/package.xml") + _size(
        sdk / "platforms/android-35/android.jar"
    )
    assert _accounted(entry) == entry.size


def test_collect_caches_splits_the_avd_folder_into_devices(tmp_path: Path) -> None:
    avd = tmp_path / "home" / ".android" / "avd"
    _write(avd / "Pixel.avd" / "userdata.img", 12000)
    _write(avd / "Pixel.ini", 80)
    entry = _collect(tmp_path / "home", tmp_path)[CacheKind.ANDROID_AVD]
    (item,) = entry.items
    assert item.id == "Pixel"
    assert [blob.path for blob in item.blobs] == ["Pixel.ini"]
    assert item.size == _size(avd / "Pixel.avd/userdata.img") + _size(avd / "Pixel.ini")
    assert _accounted(entry) == entry.size


def test_collect_caches_splits_playwright_by_browser_revision(tmp_path: Path) -> None:
    root = tmp_path / "home" / ".cache" / "ms-playwright"
    _write(root / "chromium-1243" / "chrome", 9000)
    _write(root / "chromium-1248" / "chrome", 9000)
    _write(root / "b" / "x", 300)
    entry = _collect(tmp_path / "home", tmp_path)[CacheKind.PLAYWRIGHT]
    assert sorted(item.id for item in entry.items) == ["chromium-1243", "chromium-1248"]
    assert _accounted(entry) == entry.size
    assert entry.rest.unattributed >= _size(root / "b" / "x")


def test_collect_caches_splits_jetbrains_by_product_version(tmp_path: Path) -> None:
    root = tmp_path / "home" / ".cache" / "JetBrains"
    _write(root / "PyCharm2025.1" / "caches" / "index.bin", 7000)
    _write(root / "scratch" / "x", 10)
    entry = _collect(tmp_path / "home", tmp_path)[CacheKind.JETBRAINS]
    (item,) = entry.items
    assert item.id == "PyCharm2025.1"
    assert item.size == _size(root / "PyCharm2025.1/caches/index.bin")
    assert _accounted(entry) == entry.size
