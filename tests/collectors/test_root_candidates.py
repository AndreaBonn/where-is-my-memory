import os
from pathlib import Path

import pytest

from wimm.collectors.root_candidates import (
    detect_dev_roots,
    documents_dir,
    has_git_repo,
    is_safe_candidate,
)


def write_user_dirs(home: Path, line: str) -> None:
    config = home / ".config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "user-dirs.dirs").write_text(f"# comment\n{line}\n", encoding="utf-8")


def make_repo(path: Path) -> None:
    (path / ".git").mkdir(parents=True)


def test_documents_dir_reads_localized_xdg_value(tmp_path: Path) -> None:
    (tmp_path / "Documenti").mkdir()
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/Documenti"')
    assert documents_dir(home=tmp_path) == tmp_path / "Documenti"


def test_documents_dir_missing_file_returns_none(tmp_path: Path) -> None:
    assert documents_dir(home=tmp_path) is None


@pytest.mark.parametrize("value", ["/", "$HOME", "$HOME/../..", "$HOME/a/../..", "relative/dir"])
def test_documents_dir_rejects_unsafe_values(tmp_path: Path, value: str) -> None:
    write_user_dirs(home=tmp_path, line=f'XDG_DOCUMENTS_DIR="{value}"')
    assert documents_dir(home=tmp_path) is None


def test_documents_dir_rejects_value_outside_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (tmp_path / "other").mkdir()
    write_user_dirs(home=home, line=f'XDG_DOCUMENTS_DIR="{tmp_path / "other"}"')
    assert documents_dir(home=home) is None


def test_documents_dir_rejects_symlink(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "Docs").symlink_to(tmp_path / "real")
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/Docs"')
    assert documents_dir(home=tmp_path) is None


def test_documents_dir_rejects_missing_directory(tmp_path: Path) -> None:
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/Gone"')
    assert documents_dir(home=tmp_path) is None


def test_documents_dir_unreadable_file_is_discarded(tmp_path: Path) -> None:
    config = tmp_path / ".config"
    config.mkdir()
    (config / "user-dirs.dirs").write_bytes(b"\xff\xfe\x00 not utf8")
    assert documents_dir(home=tmp_path) is None


def test_is_safe_candidate_accepts_plain_directory_in_home(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    assert is_safe_candidate(path=tmp_path / "code", home=tmp_path)
    assert not is_safe_candidate(path=tmp_path, home=tmp_path)
    assert not is_safe_candidate(path=tmp_path / "nope", home=tmp_path)


def test_has_git_repo_finds_repo_at_each_allowed_level(tmp_path: Path) -> None:
    make_repo(tmp_path / "a")
    make_repo(tmp_path / "b" / "c")
    make_repo(tmp_path / "d" / "e" / "f" / "g")
    assert has_git_repo(path=tmp_path / "a")
    assert has_git_repo(path=tmp_path / "b")
    assert not has_git_repo(path=tmp_path / "d")


def test_has_git_repo_counts_git_at_the_root_itself(tmp_path: Path) -> None:
    make_repo(tmp_path)
    assert has_git_repo(path=tmp_path)


def test_has_git_repo_does_not_follow_symlinks(tmp_path: Path) -> None:
    make_repo(tmp_path / "outside" / "repo")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path / "outside")
    assert not has_git_repo(path=root)


def test_has_git_repo_unreadable_directory_is_false(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    make_repo(locked / "r")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("permissions are not enforced for this user")
        assert not has_git_repo(path=locked)
    finally:
        locked.chmod(0o755)


def test_detect_dev_roots_returns_only_candidates_with_a_repo(tmp_path: Path) -> None:
    make_repo(tmp_path / "code" / "proj")
    (tmp_path / "src").mkdir()
    make_repo(tmp_path / "Documenti" / "x")
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/Documenti"')
    assert detect_dev_roots(home=tmp_path) == (tmp_path / "code", tmp_path / "Documenti")


def test_detect_dev_roots_skips_symlinked_candidate(tmp_path: Path) -> None:
    make_repo(tmp_path / "real" / "proj")
    (tmp_path / "code").symlink_to(tmp_path / "real")
    assert detect_dev_roots(home=tmp_path) == ()


def test_detect_dev_roots_dedups_xdg_documents_against_builtin(tmp_path: Path) -> None:
    make_repo(tmp_path / "Documenti" / "x")
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/Documenti"')
    assert detect_dev_roots(home=tmp_path) == (tmp_path / "Documenti",)


def test_detect_dev_roots_with_no_repo_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "code").mkdir()
    assert detect_dev_roots(home=tmp_path) == ()


def test_is_safe_candidate_rejects_intermediate_symlink_leaving_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "out" / "x" / "Docs"
    outside.mkdir(parents=True)
    home.mkdir(exist_ok=True)
    (home / "link").symlink_to(tmp_path / "out")
    assert not is_safe_candidate(path=home / "link" / "x" / "Docs", home=home)
    (home / "Docs").mkdir()
    assert is_safe_candidate(path=home / "Docs", home=home)
