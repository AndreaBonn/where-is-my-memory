from wimm.core.cache_items import TreeEntry, TreeListing
from wimm.core.cache_items_hf import hf_items

from .cache_items_helpers import ROOT, d, f, ln

REPO = "models--org--a"


def _sizes(*entries: TreeEntry) -> dict[str, int]:
    items, _ = hf_items(listing=TreeListing(root=ROOT, entries=entries))
    return {item.id: item.size for item in items}


def test_link_through_a_symlinked_dir_inside_the_cache_is_attributed() -> None:
    sizes = _sizes(
        d(REPO),
        d("blobs"),
        f("blobs/real", 700),
        ln("blobs-alias", "blobs"),
        ln(f"{REPO}/snapshots/rev/w", "../../../blobs-alias/real"),
    )
    assert sizes == {REPO: 700}


def test_link_through_a_symlinked_dir_leaving_the_cache_is_not_attributed() -> None:
    sizes = _sizes(
        d(REPO),
        f("blobs/real", 700),
        ln("blobs-alias", "/srv/outside"),
        ln(f"{REPO}/snapshots/rev/w", "../../../blobs-alias/real"),
    )
    assert sizes == {REPO: 0}


def test_link_through_a_chain_of_symlinked_dirs_is_attributed() -> None:
    sizes = _sizes(
        d(REPO),
        d("store"),
        f("store/real", 300),
        ln("hop2", "store"),
        ln("hop1", "hop2"),
        ln(f"{REPO}/snapshots/rev/w", "../../../hop1/real"),
    )
    assert sizes == {REPO: 300}


def test_symlinked_dir_cycle_is_dropped_without_looping() -> None:
    sizes = _sizes(
        d(REPO),
        ln("loop1", "loop2"),
        ln("loop2", "loop1"),
        ln(f"{REPO}/snapshots/rev/w", "../../../loop1/real"),
    )
    assert sizes == {REPO: 0}
