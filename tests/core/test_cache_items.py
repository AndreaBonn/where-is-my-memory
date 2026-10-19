import pytest

from wimm.core.cache_items import TreeListing, items_for
from wimm.model import CacheKind, CacheRest

from .cache_items_helpers import ROOT, d, f, hf_listing, regular_total


def test_items_and_rest_sum_to_cache_size() -> None:
    listing = hf_listing()
    size = regular_total(listing)
    items, rest = items_for(kind=CacheKind.HUGGINGFACE, listing=listing, size=size)
    assert sum(i.size for i in items) + rest.shared + rest.unattributed == size
    assert (rest.shared, rest.unattributed) == (3000, 540)
    assert sum(i.size for i in items) == 540 + 2040 + 710


def test_items_sorted_by_size_descending_ties_by_id_and_not_truncated() -> None:
    entries = [d("models--a--big"), f("models--a--big/blobs/x", 9)]
    for n in range(60):
        entries += [d(f"models--a--m{n:02d}"), f(f"models--a--m{n:02d}/blobs/x", 5)]
    listing = TreeListing(root=ROOT, entries=tuple(entries))
    items, _ = items_for(kind=CacheKind.HUGGINGFACE, listing=listing, size=9 + 60 * 5)
    assert len(items) == 61
    assert items[0].id == "models--a--big"
    assert [i.id for i in items[1:4]] == ["models--a--m00", "models--a--m01", "models--a--m02"]


WITH_A_RULE = {
    CacheKind.HUGGINGFACE,
    CacheKind.ANDROID_SDK,
    CacheKind.ANDROID_AVD,
    CacheKind.PLAYWRIGHT,
    CacheKind.JETBRAINS,
}


@pytest.mark.parametrize("kind", [k for k in CacheKind if k not in WITH_A_RULE])
def test_kind_without_a_rule_gives_no_item(kind: CacheKind) -> None:
    items, rest = items_for(kind=kind, listing=hf_listing(), size=12345)
    assert items == ()
    assert rest == CacheRest(shared=0, unattributed=0)


def test_unattributed_is_never_negative_when_listing_exceeds_size() -> None:
    listing = TreeListing(root=ROOT, entries=(d("models--a--b"), f("models--a--b/blobs/x", 100)))
    items, rest = items_for(kind=CacheKind.HUGGINGFACE, listing=listing, size=60)
    assert items[0].size == 100
    assert rest.unattributed == 0
