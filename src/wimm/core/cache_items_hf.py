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
MAX_LINK_HOPS = 40  # the kernel gives up after 40 links too: a cycle never resolves


def _repo_kind(name: str) -> tuple[str, CacheItemKind] | None:
    for prefix, kind in KIND_BY_PREFIX.items():
        if name.startswith(prefix):
            repo_id = name[len(prefix) :]
            if repo_id.replace(REPO_ID_SEPARATOR, "").strip():
                return repo_id, kind
    return None


def _inside(*, target: str, root: str) -> list[str] | None:
    """The components of an absolute link target below the root, or None if it is outside."""
    prefix = root + "/"
    if not target.startswith(prefix):
        return None
    return target[len(prefix) :].split("/")


def _target_parts(*, link: TreeEntry, root: str) -> tuple[bool, list[str]] | None:
    """(is_absolute, components) of a link target; None for an absolute one outside the root."""
    target = link.target or ""
    if not target.startswith("/"):
        return False, target.split("/")
    parts = _inside(target=target, root=root)
    return None if parts is None else (True, parts)


def _step(
    *, part: str, base: list[str], by_path: dict[str, TreeEntry]
) -> tuple[bool, TreeEntry | None]:
    """Walk one path component; (False, None) on leaving the root or a missing node."""
    if part == PARENT:
        if not base:
            return False, None
        base.pop()
        return True, None
    if part in ("", HERE):
        return True, None
    entry = by_path.get("/".join([*base, part]))
    if entry is not None and entry.type is not EntryType.SYMLINK:
        base.append(part)
    return entry is not None, entry


def _resolve(*, link: TreeEntry, by_path: dict[str, TreeEntry], root: str) -> str | None:
    """Follow a link to a regular file inside the root, one component at a time.

    A component that is itself a link is replaced by its target, so a path through a symlinked
    directory is followed. Returns None on leaving the root, a missing node or a link cycle.
    """
    base = link.path.split("/")[:-1]
    todo: list[str] = []
    hops = 0
    current: TreeEntry | None = link
    while True:
        if current is not None and current.type is EntryType.SYMLINK:
            hops += 1
            target = _target_parts(link=current, root=root)
            if hops > MAX_LINK_HOPS or target is None:
                return None
            base = [] if target[0] else base
            todo.extend(reversed(target[1]))
            current = None
        if not todo:
            return current.path if current and current.type is EntryType.FILE else None
        ok, current = _step(part=todo.pop(), base=base, by_path=by_path)
        if not ok:
            return None


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
    return CacheItem(
        id=folder.path,
        title=repo_id.replace(REPO_ID_SEPARATOR, OWNER_SEPARATOR),
        path=f"{root.rstrip('/')}/{folder.path}",
        size=size,
        st_ino=folder.st_ino,
        st_dev=folder.st_dev,
        kind=kind,
    )


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
