import pytest

from wimm.core.cache_items import EntryType, TreeEntry, TreeListing

FILE, DIR, LINK = EntryType.FILE, EntryType.DIR, EntryType.SYMLINK


def _ok() -> list[TreeEntry]:
    return [
        TreeEntry(path="a", type=DIR),
        TreeEntry(path="a/f", type=FILE, size=5),
        TreeEntry(path="a/l", type=LINK, target="f"),
    ]


def test_valid_entries_and_listing_are_accepted() -> None:
    listing = TreeListing(root="/r", entries=tuple(_ok()))
    assert [e.path for e in listing.entries] == ["a", "a/f", "a/l"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": LINK},
        {"type": LINK, "target": ""},
        {"type": LINK, "target": "   "},
        {"type": LINK, "target": 7},
        {"type": LINK, "target": "x", "size": 1},
        {"type": FILE, "target": "x"},
        {"type": DIR, "target": "x"},
        {"type": DIR, "size": 1},
        {"type": FILE, "size": -1},
        {"type": FILE, "size": 1.5},
        {"type": FILE, "st_ino": -1},
        {"type": FILE, "st_dev": True},
    ],
)
def test_illegal_entry_states_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        TreeEntry(path="p", **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("root", ["", "  ", "relative/dir", "./x"])
def test_listing_root_must_be_absolute(root: str) -> None:
    with pytest.raises(ValueError, match="root"):
        TreeListing(root=root, entries=())


def test_listing_entries_must_be_a_tuple() -> None:
    with pytest.raises(ValueError):
        TreeListing(root="/r", entries=_ok())  # type: ignore[arg-type]


@pytest.mark.parametrize("path", ["/abs", "a/../b", "..", "a/.."])
def test_listing_paths_must_be_relative_without_parent_components(path: str) -> None:
    with pytest.raises(ValueError, match="path"):
        TreeListing(root="/r", entries=(TreeEntry(path=path, type=FILE),))


def test_listing_paths_must_be_unique() -> None:
    entry = TreeEntry(path="a", type=FILE)
    with pytest.raises(ValueError, match="unique"):
        TreeListing(root="/r", entries=(entry, entry))


def test_tree_listing_rejects_a_negative_disk_bytes() -> None:
    with pytest.raises(ValueError, match="disk_bytes"):
        TreeListing(root="/r", entries=(), disk_bytes=-1)


def test_tree_listing_keeps_a_valid_disk_bytes() -> None:
    assert TreeListing(root="/r", entries=(), disk_bytes=4096).disk_bytes == 4096


def test_a_listing_defaults_to_nothing_skipped_and_refuses_a_negative_count() -> None:
    assert TreeListing(root="/r", entries=()).skipped == 0
    assert TreeListing(root="/r", entries=(), skipped=3).skipped == 3
    with pytest.raises(ValueError):
        TreeListing(root="/r", entries=(), skipped=-1)
