"""Failures and races during a tree removal: they are counted or ignored, never fatal."""

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from tests.service.fs_fakes import fingerprint_of
from wimm.service.safe_tree import empty_directory, remove_directory

real_unlink = os.unlink
real_scandir = os.scandir


def _folder(*, base: Path, files: tuple[str, ...] = ("a.txt",)) -> Path:
    folder = base / "target"
    folder.mkdir()
    for name in files:
        (folder / name).write_text("x", encoding="utf-8")
    return folder


def test_root_that_cannot_be_removed_after_its_content_is_an_error_not_a_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(base=tmp_path)
    fingerprint = fingerprint_of(path=folder)

    def busy(*_: Any, **__: Any) -> None:
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(os, "rmdir", busy)

    result = remove_directory(fingerprint=fingerprint)

    assert result.root_removed is False
    assert result.removed == 1
    assert result.error_count == 1
    assert result.error_samples == (f"{folder}: Device or resource busy",)
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_root_removal_that_succeeds_is_reported_as_removed(tmp_path: Path) -> None:
    folder = _folder(base=tmp_path)

    result = remove_directory(fingerprint=fingerprint_of(path=folder))

    assert result.root_removed is True and result.error_count == 0
    assert not folder.exists()


def test_a_missing_subfolder_is_ignored_while_the_existing_one_is_emptied(tmp_path: Path) -> None:
    trash = tmp_path / "Trash"
    (trash / "files").mkdir(parents=True)
    (trash / "files" / "y.txt").write_text("y", encoding="utf-8")

    result = empty_directory(fingerprint=fingerprint_of(path=trash), subdirs=("files", "info"))

    assert result.removed == 1
    assert result.error_count == 0 and result.error_samples == ()
    assert (trash / "files").is_dir() and list((trash / "files").iterdir()) == []
    assert not (trash / "info").exists()


def test_a_subfolder_that_cannot_be_listed_stays_and_the_rest_is_still_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(base=tmp_path, files=("keep_going.txt",))
    (folder / "locked").mkdir()
    (folder / "locked" / "inner.txt").write_text("i", encoding="utf-8")
    calls: list[int] = []

    def scandir(fd: int) -> Any:
        calls.append(fd)
        if len(calls) == 2:  # the root is listed first, then its subfolder
            raise OSError(errno.EACCES, "Permission denied")
        return real_scandir(fd)

    monkeypatch.setattr(os, "scandir", scandir)

    result = remove_directory(fingerprint=fingerprint_of(path=folder))

    assert result.root_removed is False
    assert result.error_count == 1
    assert result.error_samples == (f"{folder}/locked: Permission denied",)
    assert result.removed == 1
    assert not (folder / "keep_going.txt").exists()
    assert (folder / "locked" / "inner.txt").exists()


def test_an_entry_that_vanishes_before_its_unlink_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(base=tmp_path, files=("gone.txt", "normal.txt"))

    def unlink_after_another_process(name: str, *, dir_fd: int) -> None:
        real_unlink(name, dir_fd=dir_fd)
        if name == "gone.txt":
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(os, "unlink", unlink_after_another_process)

    result = remove_directory(fingerprint=fingerprint_of(path=folder))

    assert result.error_count == 0 and result.error_samples == ()
    assert result.removed == 1  # normal.txt: the vanished entry is nobody's removal
    assert result.root_removed is True
    assert not folder.exists()
