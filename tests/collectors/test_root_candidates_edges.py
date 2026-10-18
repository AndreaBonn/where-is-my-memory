import os
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import FailingHandle
from wimm.collectors import root_candidates
from wimm.collectors.root_candidates import documents_dir, has_git_repo, read_mountinfo


@pytest.mark.parametrize(
    ("levels_down", "expected"),
    [(0, True), (1, True), (2, True), (3, False)],
)
def test_has_git_repo_looks_down_to_two_levels_and_no_further(
    tmp_path: Path, levels_down: int, expected: bool
) -> None:
    root = tmp_path / "root"
    (root.joinpath(*("d",) * levels_down) / ".git").mkdir(parents=True)

    assert has_git_repo(path=root) is expected


def test_user_dirs_read_failure_is_treated_as_no_documents_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Docs").mkdir()
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Docs"\n')
    assert documents_dir(home=tmp_path) == tmp_path / "Docs"

    def failing_fdopen(descriptor: int, mode: str) -> Any:
        return FailingHandle(descriptor)

    monkeypatch.setattr(target=os, name="fdopen", value=failing_fdopen)

    assert documents_dir(home=tmp_path) is None


def test_read_mountinfo_gives_the_text_or_an_empty_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("22 1 8:1 / / rw - ext4 /dev/sda1 rw\n", encoding="utf-8")
    monkeypatch.setattr(target=root_candidates, name="MOUNTINFO_FILE", value=mountinfo)
    assert read_mountinfo() == "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"

    mountinfo.write_bytes(b"22 1 8:1 / /mnt/\xff\xfe rw - ext4 /dev/sda1 rw\n")
    assert read_mountinfo() == ""

    monkeypatch.setattr(target=root_candidates, name="MOUNTINFO_FILE", value=tmp_path / "gone")
    assert read_mountinfo() == ""
