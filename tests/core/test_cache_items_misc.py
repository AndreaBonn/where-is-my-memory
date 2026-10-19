from wimm.core.cache_items import TreeListing, items_for
from wimm.model import CacheItemKind
from wimm.model.disk import CacheKind

from .cache_items_helpers import d, f, regular_total

PW_ROOT = "/home/u/.cache/ms-playwright"
JB_ROOT = "/home/u/.cache/JetBrains"


def _playwright() -> TreeListing:
    entries = (
        d("chromium-1243", ino=41),
        f("chromium-1243/chrome", 6000),
        d("chromium-1248", ino=42),
        f("chromium-1248/chrome", 7000),
        d("chromium_headless_shell-1248"),
        f("chromium_headless_shell-1248/headless", 2000),
        d("ffmpeg-1013"),
        f("ffmpeg-1013/ffmpeg", 500),
        d("firefox-1500"),
        d("webkit-2100"),
        d("b"),
        f("b/stuff", 90),
        f("INSTALLATION_COMPLETE", 0),
        d("chromium-next"),
        f("chromium-next/x", 70),
    )
    return TreeListing(root=PW_ROOT, entries=entries)


def _jetbrains() -> TreeListing:
    entries = (
        d("PyCharm2025.1", ino=51),
        f("PyCharm2025.1/caches/index.bin", 4000),
        d("PyCharm2025.1/log"),
        f("PyCharm2025.1/log/idea.log", 300),
        d("IntelliJIdea2024.3"),
        f("IntelliJIdea2024.3/a", 1000),
        d("tmp"),
        f("tmp/x", 20),
        f("PyCharm2025.1.lock", 5),
    )
    return TreeListing(root=JB_ROOT, entries=entries)


def test_playwright_items_are_the_browser_revision_folders() -> None:
    listing = _playwright()
    items, _ = items_for(kind=CacheKind.PLAYWRIGHT, listing=listing, size=regular_total(listing))
    assert {item.id: item.size for item in items} == {
        "chromium-1248": 7000,
        "chromium-1243": 6000,
        "chromium_headless_shell-1248": 2000,
        "ffmpeg-1013": 500,
        "firefox-1500": 0,
        "webkit-2100": 0,
    }
    assert {item.kind for item in items} == {CacheItemKind.PLAYWRIGHT_BROWSER}
    assert items[0].path == f"{PW_ROOT}/chromium-1248"
    assert (items[0].st_ino) == 42


def test_playwright_other_folders_stay_in_the_rest() -> None:
    listing = _playwright()
    items, rest = items_for(kind=CacheKind.PLAYWRIGHT, listing=listing, size=regular_total(listing))
    assert "b" not in {item.id for item in items}
    assert "chromium-next" not in {item.id for item in items}
    assert rest.unattributed == 90 + 70


def test_playwright_sum_rule_items_plus_rest_is_the_size() -> None:
    listing = _playwright()
    items, rest = items_for(kind=CacheKind.PLAYWRIGHT, listing=listing, size=regular_total(listing))
    assert sum(i.size for i in items) + rest.shared + rest.unattributed == regular_total(listing)


def test_jetbrains_items_are_the_product_version_folders() -> None:
    listing = _jetbrains()
    items, rest = items_for(kind=CacheKind.JETBRAINS, listing=listing, size=regular_total(listing))
    assert {item.id: item.size for item in items} == {
        "PyCharm2025.1": 4300,
        "IntelliJIdea2024.3": 1000,
    }
    assert {item.kind for item in items} == {CacheItemKind.JETBRAINS_PRODUCT}
    assert items[0].title == "PyCharm2025.1"
    assert rest.unattributed == 20 + 5
    assert sum(i.size for i in items) + rest.shared + rest.unattributed == regular_total(listing)


def test_other_kinds_still_have_no_item_rule() -> None:
    listing = _jetbrains()
    items, rest = items_for(kind=CacheKind.UV, listing=listing, size=regular_total(listing))
    assert items == ()
    assert (rest.shared, rest.unattributed) == (0, 0)
