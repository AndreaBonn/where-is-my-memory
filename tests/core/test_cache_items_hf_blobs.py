import pytest

from wimm.core.cache_items import TreeListing
from wimm.core.cache_items_hf import hf_items

from .cache_items_helpers import ROOT, d, f, hf_listing, ln


def test_repo_lists_the_store_blobs_only_it_reaches() -> None:
    items, _ = hf_items(listing=hf_listing())
    by_id = {item.id: item for item in items}
    blobs = by_id["models--org--lnk"].blobs
    # the shared store blob belongs to nobody; files inside the folder go with the folder
    assert [(b.path, b.size) for b in blobs] == [("blobs/3b/excl", 2000)]
    assert by_id["models--org--std"].blobs == ()
    assert by_id["datasets--org--ds"].blobs == ()


def test_blob_carries_the_identity_of_the_store_file() -> None:
    listing = hf_listing()
    store = next(e for e in listing.entries if e.path == "blobs/3b/excl")
    items, _ = hf_items(listing=listing)
    blob = next(i for i in items if i.id == "models--org--lnk").blobs[0]
    assert (blob.st_ino, blob.st_dev) == (store.st_ino, store.st_dev)


def _linking_repo_listing(*, target: str) -> TreeListing:
    name = "models--org--one"
    entries = [
        d(name, ino=21),
        d(".locks", ino=22),
        d(".locks/x", ino=23),
        f(".locks/x/lock", 0),
        d("blobs", ino=24),
        d("blobs/ab", ino=25),
        d(f"{name}/snapshots", ino=26),
        d(f"{name}/snapshots/rev", ino=27),
        f("stray.bin", 700),
        f("blobs/ab/store", 900),
        ln(f"{name}/snapshots/rev/w", f"../../../{target}"),
    ]
    return TreeListing(root=ROOT, entries=tuple(entries), disk_bytes=0)


@pytest.mark.parametrize("target", [".locks/x/lock", "stray.bin"])
def test_a_file_outside_the_store_is_never_a_blob(target: str) -> None:
    items, _ = hf_items(listing=_linking_repo_listing(target=target))

    assert items[0].blobs == ()


def test_a_file_in_the_store_is_a_blob() -> None:
    items, _ = hf_items(listing=_linking_repo_listing(target="blobs/ab/store"))

    assert [(b.path, b.size) for b in items[0].blobs] == [("blobs/ab/store", 900)]
