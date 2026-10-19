"""Android SDK packages and virtual devices, one item each (T-6.31).

A package is a folder holding a `package.xml`. The listing carries no file contents, so the
package id is derived from the folder path: `sdkmanager` builds its package paths by joining
the folders below the SDK root with `;` (`platforms/android-35` is `platforms;android-35`).
`cmdline-tools` (sdkmanager itself) and `licenses` are never items. A device is an
`<name>.avd/` folder with its `<name>.ini` beside it; the ini goes with the device.
"""

from wimm.model.cache_items import CacheItem, ItemBlob
from wimm.model.enums import CacheItemKind

from .cache_items import EntryType, TreeEntry, TreeListing, folder_sizes

PACKAGE_FILE = "package.xml"
PACKAGE_SEPARATOR = ";"
NEVER_ITEMS = frozenset({"cmdline-tools", "licenses"})
AVD_SUFFIX = ".avd"
AVD_INI_SUFFIX = ".ini"


def _package(*, folder: TreeEntry, size: int, root: str) -> CacheItem:
    package_id = folder.path.replace("/", PACKAGE_SEPARATOR)
    return CacheItem(
        id=package_id,
        title=package_id,
        path=f"{root.rstrip('/')}/{folder.path}",
        size=size,
        st_ino=folder.st_ino,
        st_dev=folder.st_dev,
        kind=CacheItemKind.ANDROID_PACKAGE,
    )


def _package_folders(*, listing: TreeListing) -> list[TreeEntry]:
    with_xml = {
        entry.path.removesuffix(f"/{PACKAGE_FILE}")
        for entry in listing.entries
        if entry.type is EntryType.FILE and entry.path.endswith(f"/{PACKAGE_FILE}")
    }
    return [
        entry
        for entry in listing.entries
        if entry.type is EntryType.DIR
        and entry.path in with_xml
        and entry.path.split("/")[0] not in NEVER_ITEMS
    ]


def sdk_items(*, listing: TreeListing) -> tuple[tuple[CacheItem, ...], int]:
    """The package items of an SDK root (unsorted) and the bytes shared between packages."""
    folders = _package_folders(listing=listing)
    sizes, shared = folder_sizes(listing=listing, folders=[folder.path for folder in folders])
    items = tuple(
        _package(folder=folder, size=sizes[folder.path], root=listing.root) for folder in folders
    )
    return items, shared


def _device(*, folder: TreeEntry, size: int, ini: TreeEntry | None, root: str) -> CacheItem:
    name = folder.path.removesuffix(AVD_SUFFIX)
    blobs: tuple[ItemBlob, ...] = ()
    if ini is not None:
        size += ini.size
        blobs = (ItemBlob(path=ini.path, size=ini.size, st_ino=ini.st_ino, st_dev=ini.st_dev),)
    return CacheItem(
        id=name,
        title=name,
        path=f"{root.rstrip('/')}/{folder.path}",
        size=size,
        st_ino=folder.st_ino,
        st_dev=folder.st_dev,
        kind=CacheItemKind.ANDROID_AVD,
        blobs=blobs,
    )


def avd_items(*, listing: TreeListing) -> tuple[tuple[CacheItem, ...], int]:
    """The device items of an AVD root (unsorted) and the bytes shared between devices."""
    top = {entry.path: entry for entry in listing.entries if "/" not in entry.path}
    folders = [
        entry
        for entry in top.values()
        if entry.type is EntryType.DIR
        and entry.path.endswith(AVD_SUFFIX)
        and len(entry.path) > len(AVD_SUFFIX)
    ]
    sizes, shared = folder_sizes(listing=listing, folders=[folder.path for folder in folders])
    items = []
    for folder in folders:
        ini = top.get(folder.path.removesuffix(AVD_SUFFIX) + AVD_INI_SUFFIX)
        ini = ini if ini is not None and ini.type is EntryType.FILE else None
        items.append(_device(folder=folder, size=sizes[folder.path], ini=ini, root=listing.root))
    return tuple(items), shared
