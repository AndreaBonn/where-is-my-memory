from wimm.core.cache_items import EntryType, TreeEntry, TreeListing
from wimm.core.cache_items_hf import hf_items
from wimm.model import CacheItemKind

from .cache_items_helpers import (
    DEV,
    ROOT,
    d,
    dataset_repo,
    f,
    hf_listing,
    linked_repo,
    ln,
    regular_total,
    store_and_root,
)

STD = 540
LNK = 40 + 2000
DS = 710
SHARED = 3000
UNATTRIBUTED = 500 + 30 + 8 + 2


def _sizes(listing: TreeListing) -> dict[str, int]:
    items, _ = hf_items(listing=listing)
    return {item.id: item.size for item in items}


def test_repo_size_counts_exclusive_store_blobs() -> None:
    items, shared = hf_items(listing=hf_listing())
    sizes = {item.id: item.size for item in items}
    # regular blobs and the exclusive store blob count; the shared blob and the links
    # leaving the cache root (absolute and relative) do not
    assert sizes == {
        "models--org--std": STD,
        "models--org--lnk": LNK,
        "datasets--org--ds": DS,
    }
    assert shared == SHARED
    assert sum(sizes.values()) + shared + UNATTRIBUTED == regular_total(hf_listing())


def test_shared_blob_counts_for_its_only_owner_once_second_link_is_gone() -> None:
    listing = TreeListing(
        root=ROOT,
        entries=tuple([*store_and_root(), *linked_repo(), *dataset_repo(with_shared_link=False)]),
    )
    items, shared = hf_items(listing=listing)
    sizes = {item.id: item.size for item in items}
    assert sizes["models--org--lnk"] == LNK + SHARED
    assert shared == 0


def test_link_inside_root_counts_where_the_same_link_outside_does_not() -> None:
    inside = hf_listing(
        extra=(ln("models--org--std/snapshots/rev1/extra", "../../../CACHEDIR.TAG"),)
    )
    assert _sizes(inside)["models--org--std"] == STD + 8
    assert _sizes(hf_listing())["models--org--std"] == STD


def test_absolute_link_into_root_is_resolved_like_a_relative_one() -> None:
    link = ln("models--org--std/snapshots/rev1/abs", f"{ROOT}/CACHEDIR.TAG")
    assert _sizes(hf_listing(extra=(link,)))["models--org--std"] == STD + 8


def test_link_cycle_terminates_and_counts_nothing() -> None:
    listing = TreeListing(
        root=ROOT,
        entries=(d("models--o--c"), ln("models--o--c/a", "b"), ln("models--o--c/b", "a")),
    )
    assert _sizes(listing) == {"models--o--c": 0}


def test_item_metadata_comes_from_the_repo_folder() -> None:
    items, _ = hf_items(listing=hf_listing())
    by_id = {item.id: item for item in items}
    lnk = by_id["models--org--lnk"]
    assert (lnk.title, lnk.kind, lnk.path) == (
        "org/lnk",
        CacheItemKind.HF_MODEL,
        f"{ROOT}/{lnk.id}",
    )
    assert (lnk.st_ino, lnk.st_dev) == (12, DEV)
    ds = by_id["datasets--org--ds"]
    assert (ds.title, ds.kind) == ("org/ds", CacheItemKind.HF_DATASET)


def test_space_without_org_and_unknown_folders() -> None:
    listing = TreeListing(
        root=ROOT,
        entries=(
            d("spaces--demo", ino=5),
            f("spaces--demo/refs/main", 7),
            d("somethingelse"),
            f("somethingelse/x", 99),
            TreeEntry(path="models--file-not-dir", type=EntryType.FILE, size=4),
        ),
    )
    items, shared = hf_items(listing=listing)
    assert [(i.id, i.title, i.kind, i.size) for i in items] == [
        ("spaces--demo", "demo", CacheItemKind.HF_SPACE, 7)
    ]
    assert shared == 0


def test_empty_listing_has_no_items() -> None:
    assert hf_items(listing=TreeListing(root=ROOT, entries=())) == ((), 0)
