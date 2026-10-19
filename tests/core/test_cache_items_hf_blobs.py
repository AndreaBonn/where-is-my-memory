from wimm.core.cache_items_hf import hf_items

from .cache_items_helpers import hf_listing


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
