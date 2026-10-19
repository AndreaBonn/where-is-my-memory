"""Which cache items can be removed now (T-6.32, T-6.33).

Android items go only through their tool, so without it nothing is offered. The tool is looked
for in the SDK roots first, where Android Studio installs it off PATH, then on PATH. The file
checks are injected: the service and the page ask the same question with their own I/O.
"""

from collections.abc import Callable, Iterable, Mapping
from pathlib import PurePath
from types import MappingProxyType

from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind
from wimm.model.enums import CacheItemKind

ITEM_TOOLS: Mapping[CacheKind, str] = MappingProxyType(
    {CacheKind.ANDROID_SDK: "sdkmanager", CacheKind.ANDROID_AVD: "avdmanager"}
)
SDK_TOOLS_DIR = PurePath("cmdline-tools/latest/bin")


def item_tool(
    *,
    kind: CacheKind,
    sdk_roots: Iterable[str],
    is_executable: Callable[[str], bool],
    which: Callable[[str], str | None],
) -> str | None:
    """The absolute path of the tool that removes items of `kind`, or None."""
    name = ITEM_TOOLS[kind]
    for root in sdk_roots:
        candidate = str(PurePath(root) / SDK_TOOLS_DIR / name)
        if is_executable(candidate):
            return candidate
    found = which(name)
    return found if found is not None and PurePath(found).is_absolute() else None


def withheld_item_kinds(
    *,
    sdk_roots: Iterable[str],
    is_executable: Callable[[str], bool],
    which: Callable[[str], str | None],
) -> frozenset[CacheKind]:
    """The item kinds whose tool is missing: their items are shown, never offered."""
    roots = tuple(sdk_roots)
    return frozenset(
        kind
        for kind in ITEM_TOOLS
        if item_tool(kind=kind, sdk_roots=roots, is_executable=is_executable, which=which) is None
    )


def is_item_removable(*, item: CacheItem) -> bool:
    """An AVD without its .ini cannot go: avdmanager finds the device through that file."""
    return item.kind is not CacheItemKind.ANDROID_AVD or bool(item.blobs)


# Kinds with no folder behind them: only their items are offered, never the whole entry.
ITEM_ONLY_KINDS = frozenset({CacheKind.OLLAMA_SYSTEM})
