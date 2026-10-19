import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from wimm.collectors.cache_items import list_tree
from wimm.core.cache_items import EntryType, TreeEntry


def _noop(_seconds: float) -> None:
    return None


def _by_path(root: Path) -> dict[str, TreeEntry]:
    return {entry.path: entry for entry in list_tree(root=root, sleep=_noop).entries}


def _blocks(path: Path) -> int:
    return os.lstat(path).st_blocks * 512


def test_list_tree_reports_files_dirs_and_links_relative_to_root(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f.bin").write_bytes(b"x" * 5000)
    (root / "a" / "link").symlink_to("b/f.bin")
    listing = list_tree(root=root, sleep=_noop)
    found = {entry.path: entry for entry in listing.entries}
    assert listing.root == str(root)
    assert set(found) == {"a", "a/b", "a/b/f.bin", "a/link"}
    assert found["a"].type is EntryType.DIR
    assert found["a"].st_ino == os.lstat(root / "a").st_ino
    assert found["a"].st_dev == os.lstat(root / "a").st_dev
    assert found["a/b/f.bin"].type is EntryType.FILE
    assert found["a/b/f.bin"].size == _blocks(root / "a" / "b" / "f.bin")
    assert found["a/link"].type is EntryType.SYMLINK
    assert found["a/link"].target == "b/f.bin"
    assert found["a/link"].size == 0


def test_list_tree_never_follows_or_resolves_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"y" * 8192)
    root = tmp_path / "tree"
    root.mkdir()
    (root / "to_file").symlink_to(outside / "secret.bin")
    (root / "to_dir").symlink_to(outside)

    def forbidden(*args: object, **kwargs: object) -> str:
        raise AssertionError("realpath must not be called")

    monkeypatch.setattr(os.path, "realpath", forbidden)
    monkeypatch.setattr(Path, "resolve", forbidden)
    found = _by_path(root)
    assert set(found) == {"to_file", "to_dir"}
    assert found["to_file"].target == str(outside / "secret.bin")
    assert found["to_dir"].type is EntryType.SYMLINK
    assert all(entry.size == 0 for entry in found.values())


def test_list_tree_keeps_the_size_on_every_hard_link_with_one_shared_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "one.bin").write_bytes(b"z" * 8192)
    os.link(root / "one.bin", root / "two.bin")
    entries = list_tree(root=root, sleep=_noop).entries
    assert [entry.size for entry in entries] == [_blocks(root / "one.bin")] * 2
    assert entries[0].size > 0
    assert len({(entry.st_dev, entry.st_ino) for entry in entries}) == 1


def test_list_tree_skips_unreadable_directory_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    (root / "open").mkdir(parents=True)
    (root / "open" / "f").write_bytes(b"1")
    locked = root / "locked"
    locked.mkdir()
    (locked / "hidden").write_bytes(b"2")
    real_scandir = os.scandir

    def scandir(fd: int) -> Iterator[os.DirEntry[str]]:
        # A permission check is not portable (root, some sandboxes read anyway): fake it.
        if os.readlink(f"/proc/self/fd/{fd}") == str(locked):
            raise PermissionError(13, "Permission denied", str(locked))
        return real_scandir(fd)

    monkeypatch.setattr(os, "scandir", scandir)

    found = _by_path(root)

    assert "open/f" in found
    assert "locked" in found
    assert "locked/hidden" not in found


def test_list_tree_of_missing_root_is_empty(tmp_path: Path) -> None:
    assert list_tree(root=tmp_path / "gone", sleep=_noop).entries == ()
