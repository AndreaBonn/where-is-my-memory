"""Ollama models, one item per manifest `manifests/<host>/<namespace>/<name>/<tag>` (T-6.36).

A model owns the layer blobs its manifest names (config included). A blob named by two or more
manifests is shared and belongs to the rest of the cache. A manifest that cannot be read, parsed
or trusted is not an item and the blobs it would name stay unattributed.
"""

import json
import re
from collections import defaultdict
from json import JSONDecodeError

from wimm.model.cache_items import CacheItem
from wimm.model.enums import CacheItemKind

from .cache_items import EntryType, TreeEntry, TreeListing

MANIFEST_DIR = "manifests"
MANIFEST_DEPTH = 5  # manifests/<host>/<namespace>/<name>/<tag>
DIGEST = re.compile(r"sha256:(?P<hex>[0-9a-f]{64})")
BLOB_PREFIX = "blobs/sha256-"
DEFAULT_HOST = "registry.ollama.ai"
DEFAULT_NAMESPACE = "library"


def display_name(*, parts: list[str]) -> str:
    """The name `ollama rm` takes for `[manifests, host, namespace, name, tag]`."""
    _, host, namespace, name, tag = parts
    prefix = "" if namespace == DEFAULT_NAMESPACE and host == DEFAULT_HOST else f"{namespace}/"
    host_part = "" if host == DEFAULT_HOST else f"{host}/"
    return f"{host_part}{prefix}{name}:{tag}"


def _digests(*, text: str) -> frozenset[str] | None:
    """The blob digests a manifest names (config and layers), None when it cannot be trusted."""
    try:
        manifest = json.loads(text)
    except (JSONDecodeError, RecursionError):
        return None
    if not isinstance(manifest, dict):
        return None
    config, layers = manifest.get("config"), manifest.get("layers")
    if not isinstance(config, dict) or not isinstance(layers, list):
        return None
    named = [
        config.get("digest"),
        *(layer.get("digest") if isinstance(layer, dict) else None for layer in layers),
    ]
    found: set[str] = set()
    for digest in named:
        matched = DIGEST.fullmatch(digest) if isinstance(digest, str) else None
        if matched is None:
            return None
        found.add(matched.group("hex"))
    return frozenset(found)


def _models(*, listing: TreeListing) -> dict[str, frozenset[str]]:
    """Manifest path -> digests, for every manifest file of the listing that parses."""
    files = {e.path for e in listing.entries if e.type is EntryType.FILE}
    models: dict[str, frozenset[str]] = {}
    for path, text in listing.texts:
        parts = path.split("/")
        if path not in files or len(parts) != MANIFEST_DEPTH or parts[0] != MANIFEST_DIR:
            continue
        digests = _digests(text=text)
        if digests is not None:
            models[path] = digests
    return models


def _blob_sizes(*, listing: TreeListing) -> dict[str, int]:
    return {
        entry.path.removeprefix(BLOB_PREFIX): entry.size
        for entry in listing.entries
        if entry.type is EntryType.FILE and entry.path.startswith(BLOB_PREFIX)
    }


def ollama_items(*, listing: TreeListing) -> tuple[tuple[CacheItem, ...], int]:
    """The model items of an ollama store (unsorted) and the bytes shared between models."""
    models = _models(listing=listing)
    sizes = _blob_sizes(listing=listing)
    owners: dict[str, set[str]] = defaultdict(set)
    for path, digests in models.items():
        for digest in digests:
            owners[digest].add(path)
    own = dict.fromkeys(models, 0)
    shared = 0
    for digest, paths in owners.items():
        if len(paths) > 1:
            shared += sizes.get(digest, 0)
        else:
            own[next(iter(paths))] += sizes.get(digest, 0)
    by_path: dict[str, TreeEntry] = {e.path: e for e in listing.entries}
    root = listing.root.rstrip("/")
    items = tuple(
        CacheItem(
            id=display_name(parts=path.split("/")),
            title=display_name(parts=path.split("/")),
            path=f"{root}/{path}",
            size=size,
            st_ino=by_path[path].st_ino,
            st_dev=by_path[path].st_dev,
            kind=CacheItemKind.OLLAMA_MODEL,
        )
        for path, size in own.items()
    )
    return items, shared
