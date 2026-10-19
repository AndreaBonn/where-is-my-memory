"""HuggingFace hub cache: one item per cached repo, links resolved inside the cache root.

A repo's `snapshots/` hold symlinks to its own `blobs/`, which are either regular files or
links into the hub-wide store `blobs/<2 hex>/<sha>`. A regular file counts for every repo
that owns it by folder or reaches it through a link; files are told apart by identity
(device, inode), so a hard link counts once and one claimed by two or more repos is shared
and belongs to no item.
"""

import posixpath
from collections import defaultdict
from types import MappingProxyType

from wimm.model.cache_items import CacheItem
from wimm.model.enums import CacheItemKind

from .cache_items import EntryType, TreeEntry, TreeListing

KIND_BY_PREFIX = MappingProxyType(
    {
        "models--": CacheItemKind.HF_MODEL,
        "datasets--": CacheItemKind.HF_DATASET,
        "spaces--": CacheItemKind.HF_SPACE,
    }
)
REPO_ID_SEPARATOR = "--"
OWNER_SEPARATOR = "/"
PARENT = ".."
HERE = "."


def _repo_kind(name: str) -> tuple[str, CacheItemKind] | None:
    for prefix, kind in KIND_BY_PREFIX.items():
        if name.startswith(prefix):
            repo_id = name[len(prefix) :]
            if repo_id.replace(REPO_ID_SEPARATOR, "").strip():
                return repo_id, kind
    return None


def _inside_root(*, link: TreeEntry, root: str) -> str | None:
    """The normalized root-relative path a link points at, or None if it leaves the root."""
    target = link.target or ""
    if target.startswith("/"):
        prefix = root + "/"
        absolute = posixpath.normpath(target)
        if not absolute.startswith(prefix):
            return None
        relative = absolute[len(prefix) :]
    else:
        relative = posixpath.normpath(posixpath.join(posixpath.dirname(link.path), target))
    if relative in (PARENT, HERE) or relative.startswith(PARENT + "/"):
        return None
    return relative


def _resolve(*, link: TreeEntry, by_path: dict[str, TreeEntry], root: str) -> str | None:
    """Follow a link chain to a regular file inside the root; None on leaving it or a cycle."""
    seen: set[str] = set()
    current = link
    while current.type is EntryType.SYMLINK:
        if current.path in seen:
            return None
        seen.add(current.path)
        relative = _inside_root(link=current, root=root)
        if relative is None or relative not in by_path:
            return None
        current = by_path[relative]
    return current.path if current.type is EntryType.FILE else None


Identity = tuple[int, int]


def _identity(entry: TreeEntry) -> Identity:
    return (entry.st_dev, entry.st_ino)


def _claims(*, listing: TreeListing, repos: set[str]) -> dict[Identity, set[str]]:
    """Map every regular file a repo owns or reaches, by identity, to the repos claiming it."""
    root = posixpath.normpath(listing.root)
    by_path = {entry.path: entry for entry in listing.entries}
    claims: dict[Identity, set[str]] = defaultdict(set)
    for entry in listing.entries:
        owner = entry.path.split(OWNER_SEPARATOR, 1)[0]
        if owner not in repos or entry.path == owner:
            continue
        if entry.type is EntryType.FILE:
            claims[_identity(entry)].add(owner)
        elif entry.type is EntryType.SYMLINK:
            reached = _resolve(link=entry, by_path=by_path, root=root)
            if reached is not None:
                claims[_identity(by_path[reached])].add(owner)
    return claims


def _make_item(*, folder: TreeEntry, size: int, root: str) -> CacheItem | None:
    parsed = _repo_kind(folder.path)
    if parsed is None:
        return None
    repo_id, kind = parsed
    try:
        return CacheItem(
            id=folder.path,
            title=repo_id.replace(REPO_ID_SEPARATOR, OWNER_SEPARATOR),
            path=f"{root.rstrip('/')}/{folder.path}",
            size=size,
            st_ino=folder.st_ino,
            st_dev=folder.st_dev,
            kind=kind,
        )
    except ValueError:
        # An odd folder name must never take the whole report down; it is just not an item.
        return None


def hf_items(*, listing: TreeListing) -> tuple[tuple[CacheItem, ...], int]:
    """The repo items of a hub cache (unsorted) and the bytes shared between repos."""
    folders = {
        entry.path: entry
        for entry in listing.entries
        if entry.type is EntryType.DIR
        and OWNER_SEPARATOR not in entry.path
        and _repo_kind(entry.path) is not None
    }
    sizes = {_identity(e): e.size for e in listing.entries if e.type is EntryType.FILE}
    per_repo = dict.fromkeys(folders, 0)
    shared = 0
    for identity, owners in _claims(listing=listing, repos=set(folders)).items():
        if len(owners) > 1:
            shared += sizes[identity]
        else:
            per_repo[next(iter(owners))] += sizes[identity]
    made = (
        _make_item(folder=folder, size=per_repo[name], root=listing.root)
        for name, folder in folders.items()
    )
    return tuple(item for item in made if item is not None), shared
