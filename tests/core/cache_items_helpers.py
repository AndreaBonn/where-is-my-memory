from wimm.core.cache_items import EntryType, TreeEntry, TreeListing

ROOT = "/home/u/.cache/huggingface/hub"
DEV = 64768


def d(path: str, *, ino: int = 1) -> TreeEntry:
    return TreeEntry(path=path, type=EntryType.DIR, st_ino=ino, st_dev=DEV)


def f(path: str, size: int) -> TreeEntry:
    return TreeEntry(path=path, type=EntryType.FILE, size=size)


def ln(path: str, target: str) -> TreeEntry:
    return TreeEntry(path=path, type=EntryType.SYMLINK, target=target)


def standard_repo() -> list[TreeEntry]:
    """Standard huggingface_hub layout: regular blobs, snapshots link to them (540 B)."""
    name = "models--org--std"
    return [
        d(name, ino=11),
        f(f"{name}/blobs/h1", 400),
        f(f"{name}/blobs/h2", 100),
        f(f"{name}/refs/main", 40),
        ln(f"{name}/snapshots/rev1/model.bin", "../../blobs/h1"),
        ln(f"{name}/snapshots/rev1/config.json", "../../blobs/h2"),
    ]


def linked_repo(*, outside_target: str = "/srv/outside/leak") -> list[TreeEntry]:
    """Blobs are links into the hub store: one exclusive (2000 B), one shared (3000 B)."""
    name = "models--org--lnk"
    return [
        d(name, ino=12),
        f(f"{name}/refs/main", 40),
        ln(f"{name}/blobs/s1", "../../blobs/3b/excl"),
        ln(f"{name}/blobs/s2", "../../blobs/3b/shr"),
        ln(f"{name}/snapshots/rev/w1", "../../blobs/s1"),
        ln(f"{name}/snapshots/rev/w2", "../../blobs/s2"),
        ln(f"{name}/snapshots/rev/out", outside_target),
        ln(f"{name}/snapshots/rev/up", "../../../../../outside"),
        ln(f"{name}/snapshots/rev/loop1", "loop2"),
        ln(f"{name}/snapshots/rev/loop2", "loop1"),
    ]


def dataset_repo(*, with_shared_link: bool = True) -> list[TreeEntry]:
    """Dataset whose only store link points at the blob the linked repo also reaches."""
    name = "datasets--org--ds"
    entries = [d(name, ino=13), f(f"{name}/blobs/d2", 700), f(f"{name}/refs/main", 10)]
    if with_shared_link:
        entries.append(ln(f"{name}/blobs/d1", "../../blobs/3b/shr"))
        entries.append(ln(f"{name}/snapshots/rev/d1", "../../blobs/d1"))
    return entries


def store_and_root() -> list[TreeEntry]:
    return [
        d("blobs"),
        d("blobs/3b"),
        f("blobs/3b/excl", 2000),
        f("blobs/3b/shr", 3000),
        d("blobs/7f"),
        f("blobs/7f/orphan", 500),
        d(".locks"),
        f(".locks/lock1", 30),
        f("CACHEDIR.TAG", 8),
        f("version_diffusers_cache.txt", 2),
    ]


def hf_listing(*, extra: tuple[TreeEntry, ...] = ()) -> TreeListing:
    entries = [*store_and_root(), *standard_repo(), *linked_repo(), *dataset_repo(), *extra]
    return TreeListing(root=ROOT, entries=tuple(entries))


def regular_total(listing: TreeListing) -> int:
    return sum(e.size for e in listing.entries if e.type is EntryType.FILE)
