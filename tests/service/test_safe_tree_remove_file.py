import os
from pathlib import Path

import pytest

from wimm.service.errors import TargetChanged
from wimm.service.safe_tree import remove_file


def make_file(*, root: Path, relative: str) -> os.stat_result:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 4096)
    return os.lstat(path)


def test_remove_file_unlinks_the_planned_file_and_counts_its_bytes(tmp_path: Path) -> None:
    info = make_file(root=tmp_path, relative="blobs/ab/f")

    result = remove_file(
        root=str(tmp_path), relative="blobs/ab/f", st_ino=info.st_ino, st_dev=info.st_dev
    )

    assert not (tmp_path / "blobs/ab/f").exists()
    assert result.removed == 1
    assert result.freed_bytes == info.st_blocks * 512


def test_remove_file_refuses_a_symlinked_parent_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    info = make_file(root=outside, relative="f")
    root = tmp_path / "root"
    root.mkdir()
    (root / "blobs").symlink_to(outside)

    with pytest.raises(TargetChanged):
        remove_file(root=str(root), relative="blobs/f", st_ino=info.st_ino, st_dev=info.st_dev)
    assert (outside / "f").exists()


def test_remove_file_refuses_a_replaced_inode(tmp_path: Path) -> None:
    info = make_file(root=tmp_path, relative="blobs/f")
    replacement = tmp_path / "blobs" / "new"
    replacement.write_bytes(b"other")
    os.rename(replacement, tmp_path / "blobs" / "f")

    with pytest.raises(TargetChanged):
        remove_file(root=str(tmp_path), relative="blobs/f", st_ino=info.st_ino, st_dev=info.st_dev)
    assert (tmp_path / "blobs" / "f").read_bytes() == b"other"


def test_remove_file_refuses_a_symlink_in_place_of_the_file(tmp_path: Path) -> None:
    target = tmp_path / "target"
    info = make_file(root=tmp_path, relative="target")
    (tmp_path / "blobs").mkdir()
    (tmp_path / "blobs" / "f").symlink_to(target)

    with pytest.raises(TargetChanged):
        remove_file(root=str(tmp_path), relative="blobs/f", st_ino=info.st_ino, st_dev=info.st_dev)
    assert target.exists()


def test_remove_file_reports_a_missing_file_as_not_found(tmp_path: Path) -> None:
    (tmp_path / "blobs").mkdir()

    with pytest.raises(FileNotFoundError):
        remove_file(root=str(tmp_path), relative="blobs/f", st_ino=1, st_dev=1)


def test_remove_file_refuses_a_relative_path_leaving_the_root(tmp_path: Path) -> None:
    info = make_file(root=tmp_path, relative="f")
    (tmp_path / "root").mkdir()

    with pytest.raises(TargetChanged):
        remove_file(
            root=str(tmp_path / "root"), relative="../f", st_ino=info.st_ino, st_dev=info.st_dev
        )
    assert (tmp_path / "f").exists()
