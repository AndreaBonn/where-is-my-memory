"""Playwright browsers and JetBrains product folders, one item per top-level folder (T-6.34).

Only a folder named like a known item is an item; anything else at the root (the `b/` folder
of Playwright, scratch or lock files) stays in the rest of the cache.
"""

import re

from wimm.model.cache_items import CacheItem
from wimm.model.enums import CacheItemKind

from .cache_items import EntryType, TreeListing, folder_sizes

BROWSER_FOLDER = re.compile(r"(chromium|chromium_headless_shell|firefox|webkit|ffmpeg)-\d+")
PRODUCT_FOLDER = re.compile(r"[A-Za-z]+\d{4}\.\d+")


def _folder_items(
    *, listing: TreeListing, pattern: re.Pattern[str], kind: CacheItemKind
) -> tuple[tuple[CacheItem, ...], int]:
    folders = [
        entry
        for entry in listing.entries
        if entry.type is EntryType.DIR and pattern.fullmatch(entry.path)
    ]
    sizes, shared = folder_sizes(listing=listing, folders=[folder.path for folder in folders])
    items = tuple(
        CacheItem(
            id=folder.path,
            title=folder.path,
            path=f"{listing.root.rstrip('/')}/{folder.path}",
            size=sizes[folder.path],
            st_ino=folder.st_ino,
            st_dev=folder.st_dev,
            kind=kind,
        )
        for folder in folders
    )
    return items, shared


def playwright_items(*, listing: TreeListing) -> tuple[tuple[CacheItem, ...], int]:
    """The browser-revision items of a Playwright cache (unsorted) and the shared bytes."""
    return _folder_items(
        listing=listing, pattern=BROWSER_FOLDER, kind=CacheItemKind.PLAYWRIGHT_BROWSER
    )


def jetbrains_items(*, listing: TreeListing) -> tuple[tuple[CacheItem, ...], int]:
    """The product-version items of a JetBrains cache (unsorted) and the shared bytes."""
    return _folder_items(
        listing=listing, pattern=PRODUCT_FOLDER, kind=CacheItemKind.JETBRAINS_PRODUCT
    )
