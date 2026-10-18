import os
from pathlib import Path

import pytest

from wimm.collectors.root_candidates import (
    detect_dev_roots,
    documents_dir,
    has_git_repo,
    is_network_path,
    is_safe_candidate,
    parse_mountinfo,
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


def test_has_git_repo_finds_a_repo_exactly_two_levels_below(tmp_path: Path) -> None:
    make_repo(tmp_path / "p" / "q" / "r")
    assert has_git_repo(path=tmp_path / "p")


def test_documents_dir_ignores_a_symlinked_user_dirs_file(tmp_path: Path) -> None:
    (tmp_path / "Documenti").mkdir()
    real = tmp_path / "elsewhere.dirs"
    real.write_text('XDG_DOCUMENTS_DIR="$HOME/Documenti"\n', encoding="utf-8")
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").symlink_to(real)
    assert documents_dir(home=tmp_path) is None


def test_is_safe_candidate_refuses_a_directory_whose_lstat_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "code").mkdir()
    assert is_safe_candidate(path=tmp_path / "code", home=tmp_path)

    def denied(path: object) -> os.stat_result:
        raise PermissionError(path)

    monkeypatch.setattr(os, "lstat", denied)
    assert not is_safe_candidate(path=tmp_path / "code", home=tmp_path)


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


MOUNTINFO = (
    "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"
    "36 22 0:40 / /mnt/nas rw,relatime shared:2 - nfs4 srv:/export rw\n"
    "37 22 0:41 / /mnt/My\\040Share rw - cifs //srv/x rw\n"
    "38 36 0:42 / /mnt/nas/local rw - ext4 /dev/sdb1 rw\n"
    "39 22 0:43 / /mnt/ntfs rw - fuseblk /dev/sdc1 rw\n"
    "40 22 0:44 / /mnt/ssh rw - fuse.sshfs me@host:/ rw\n"
    "41 22 0:45 / /mnt/auto rw - autofs systemd-1 rw\n"
    "garbage line\n"
)


def test_parse_mountinfo_reads_mountpoint_and_fstype_and_unescapes_spaces() -> None:
    mounts = dict(parse_mountinfo(text=MOUNTINFO))
    assert mounts[Path("/")] == "ext4"
    assert mounts[Path("/mnt/nas")] == "nfs4"
    assert mounts[Path("/mnt/My Share")] == "cifs"
    assert len(mounts) == 7


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/mnt/nas/projects", True),
        ("/mnt/My Share/code", True),
        ("/mnt/ssh/code", True),
        ("/mnt/auto/code", True),
        ("/mnt/nas/local/code", False),
        ("/mnt/ntfs/code", False),
        ("/home/me/code", False),
        ("/mnt/nas2/code", False),
    ],
)
def test_is_network_path_uses_the_longest_matching_mount(path: str, expected: bool) -> None:
    mounts = parse_mountinfo(text=MOUNTINFO)
    assert is_network_path(path=Path(path), mounts=mounts) is expected


def test_is_network_path_without_mounts_is_false() -> None:
    assert not is_network_path(path=Path("/mnt/nas/x"), mounts=())


def test_detect_dev_roots_skips_candidates_on_network_filesystems(tmp_path: Path) -> None:
    make_repo(tmp_path / "code" / "a")
    make_repo(tmp_path / "projects" / "b")
    line = f"50 22 0:60 / {tmp_path / 'code'} rw - nfs4 srv:/x rw\n"
    roots = detect_dev_roots(home=tmp_path, read_mounts=lambda: line)
    assert roots == (tmp_path / "projects",)


def test_detect_dev_roots_keeps_candidates_when_mountinfo_is_unreadable(tmp_path: Path) -> None:
    make_repo(tmp_path / "code" / "a")
    assert detect_dev_roots(home=tmp_path, read_mounts=lambda: "") == (tmp_path / "code",)


def test_detect_dev_roots_logs_nothing_for_absent_candidates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    make_repo(tmp_path / "code" / "a")
    with caplog.at_level("DEBUG"):
        assert detect_dev_roots(home=tmp_path, read_mounts=lambda: "") == (tmp_path / "code",)
    assert caplog.records == []


def test_is_network_path_lets_the_last_mount_on_a_point_win() -> None:
    over_local = ((Path("/mnt/data"), "nfs4"), (Path("/mnt/data"), "ext4"))
    over_network = ((Path("/mnt/data"), "ext4"), (Path("/mnt/data"), "nfs4"))
    assert not is_network_path(path=Path("/mnt/data/code"), mounts=over_local)
    assert is_network_path(path=Path("/mnt/data/code"), mounts=over_network)


def test_documents_dir_ignores_a_fifo_instead_of_blocking(tmp_path: Path) -> None:
    (tmp_path / ".config").mkdir(exist_ok=True)
    os.mkfifo(tmp_path / ".config" / "user-dirs.dirs")
    assert documents_dir(home=tmp_path) is None
    (tmp_path / ".config" / "user-dirs.dirs").unlink()
    (tmp_path / "Docs").mkdir()
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/Docs"')
    assert documents_dir(home=tmp_path) == tmp_path / "Docs"


def test_documents_dir_refuses_a_hidden_folder(tmp_path: Path) -> None:
    (tmp_path / ".cargo" / "git").mkdir(parents=True)
    write_user_dirs(home=tmp_path, line='XDG_DOCUMENTS_DIR="$HOME/.cargo"')
    assert documents_dir(home=tmp_path) is None


def test_detect_dev_roots_never_stats_a_candidate_on_a_network_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import wimm.collectors.root_candidates as module

    make_repo(tmp_path / "code" / "app")
    probed: list[Path] = []
    real_check = module.is_safe_candidate

    def recording(path: Path, home: Path) -> bool:
        probed.append(path)
        return real_check(path=path, home=home)

    monkeypatch.setattr(module, "is_safe_candidate", recording)
    mounts = f"36 1 0:40 / {tmp_path / 'code'} rw - nfs4 server:/x rw\n"
    assert detect_dev_roots(home=tmp_path, read_mounts=lambda: mounts) == ()
    assert tmp_path / "code" not in probed
    assert detect_dev_roots(home=tmp_path, read_mounts=lambda: "") == (tmp_path / "code",)
