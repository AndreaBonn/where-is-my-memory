from pathlib import Path

import pytest

from wimm.collectors.cache_items import MAX_TEXT_BYTES, list_tree


def _noop(_seconds: float) -> None:
    return None


def _tree(root: Path) -> Path:
    (root / "manifests" / "h" / "n" / "m").mkdir(parents=True)
    (root / "blobs").mkdir()
    (root / "manifests" / "h" / "n" / "m" / "t").write_text('{"a": 1}')
    (root / "blobs" / "other").write_text("not a manifest")
    return root


def _texts(root: Path, prefix: str = "manifests/") -> dict[str, str]:
    return dict(list_tree(root=root, sleep=_noop, text_prefix=prefix).texts)


def test_files_under_the_prefix_are_read_and_the_others_are_not(tmp_path: Path) -> None:
    assert _texts(_tree(tmp_path / "t")) == {"manifests/h/n/m/t": '{"a": 1}'}


def test_without_a_prefix_no_file_is_read(tmp_path: Path) -> None:
    listing = list_tree(root=_tree(tmp_path / "t"), sleep=_noop)
    assert listing.texts == ()
    assert "manifests/h/n/m/t" in {e.path for e in listing.entries}


def test_an_oversized_file_is_skipped_but_still_listed(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    big = root / "manifests" / "h" / "n" / "m" / "big"
    big.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    listing = list_tree(root=root, sleep=_noop, text_prefix="manifests/")
    assert dict(listing.texts) == {"manifests/h/n/m/t": '{"a": 1}'}
    assert "manifests/h/n/m/big" in {e.path for e in listing.entries}


def test_a_file_of_exactly_the_limit_is_read(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    (root / "manifests" / "h" / "n" / "m" / "edge").write_bytes(b"x" * MAX_TEXT_BYTES)
    assert len(_texts(root)["manifests/h/n/m/edge"]) == MAX_TEXT_BYTES


def test_a_symlink_is_never_followed_to_read_its_target(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (root / "manifests" / "h" / "n" / "m" / "link").symlink_to(outside)
    assert set(_texts(root)) == {"manifests/h/n/m/t"}


def test_a_file_that_is_not_utf8_is_skipped(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    (root / "manifests" / "h" / "n" / "m" / "bin").write_bytes(b"\xff\xfe\x00")
    assert set(_texts(root)) == {"manifests/h/n/m/t"}


def test_an_unreadable_file_does_not_fail_the_scan(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    locked = root / "manifests" / "h" / "n" / "m" / "locked"
    locked.write_text("{}")
    locked.chmod(0)
    try:
        listing = list_tree(root=root, sleep=_noop, text_prefix="manifests/")
    finally:
        locked.chmod(0o600)
    if (tmp_path / "t").stat().st_uid == 0:
        pytest.skip("root reads any file")
    assert dict(listing.texts) == {"manifests/h/n/m/t": '{"a": 1}'}
    assert "manifests/h/n/m/locked" in {e.path for e in listing.entries}
