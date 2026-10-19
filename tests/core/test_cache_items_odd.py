import pytest

from wimm.core.cache_items import TreeListing, items_for
from wimm.core.cache_items_hf import hf_items
from wimm.model import CacheKind

from .cache_items_helpers import ROOT, d, f

FOLDERS = ["models-- ", "models--", "models--   ", "datasets----", "spaces-- --"]


@pytest.mark.parametrize("folder", FOLDERS)
def test_repo_folder_with_a_blank_id_is_not_an_item_and_its_bytes_are_unattributed(
    folder: str,
) -> None:
    listing = TreeListing(
        root=ROOT,
        entries=(
            d(folder, ino=3),
            f(f"{folder}/blobs/x", 50),
            d("models--org--ok", ino=4),
            f("models--org--ok/blobs/y", 70),
        ),
    )
    items, rest = items_for(kind=CacheKind.HUGGINGFACE, listing=listing, size=120)
    assert [(i.id, i.size) for i in items] == [("models--org--ok", 70)]
    assert (rest.shared, rest.unattributed) == (0, 0 + 50)


def test_hard_link_inside_one_repo_counts_once_in_that_repo() -> None:
    listing = TreeListing(
        root=ROOT,
        entries=(
            d("models--o--a", ino=3),
            f("models--o--a/blobs/one", 8192, ino=900),
            f("models--o--a/blobs/two", 8192, ino=900),
        ),
    )
    items, shared = hf_items(listing=listing)
    assert [(i.id, i.size) for i in items] == [("models--o--a", 8192)]
    assert shared == 0


def test_hard_link_across_two_repos_is_shared_and_in_neither() -> None:
    listing = TreeListing(
        root=ROOT,
        entries=(
            d("models--o--a", ino=3),
            f("models--o--a/blobs/x", 8192, ino=900),
            d("models--o--b", ino=4),
            f("models--o--b/blobs/x", 8192, ino=900),
            f("models--o--b/blobs/own", 100),
        ),
    )
    items, shared = hf_items(listing=listing)
    assert {i.id: i.size for i in items} == {"models--o--a": 0, "models--o--b": 100}
    assert shared == 8192


def test_hard_linked_bytes_reached_by_no_repo_stay_unattributed() -> None:
    listing = TreeListing(
        root=ROOT,
        entries=(
            d("models--o--a", ino=3),
            f("models--o--a/blobs/x", 8192, ino=900),
            f("blobs/ab/x", 8192, ino=900),
            f("blobs/ab/other", 4096),
        ),
    )
    items, rest = items_for(kind=CacheKind.HUGGINGFACE, listing=listing, size=8192 + 4096)
    assert [(i.id, i.size) for i in items] == [("models--o--a", 8192)]
    assert (rest.shared, rest.unattributed) == (0, 4096)
