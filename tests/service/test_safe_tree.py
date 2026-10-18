import os
import sys
from pathlib import Path

import pytest

from tests.service.fs_fakes import fingerprint_of
from wimm.model.actions import DirFingerprint
from wimm.service import safe_tree
from wimm.service.errors import ControlFailed, TargetChanged
from wimm.service.fs_controls import PsutilCwds, SubprocessRunner
from wimm.service.safe_tree import empty_directory, parse_mountinfo, remove_directory

MOUNTINFO = (
    "36 35 98:0 /mnt1 /mnt2 rw,noatime master:1 - ext3 /dev/root rw,errors=continue\n"
    "40 36 8:1 / /home/u/with\\040space rw - ext4 /dev/sda1 rw\n"
    "garbage\n"
)


def tree(*, base: Path) -> Path:
    (base / "a" / "b").mkdir(parents=True)
    (base / "a" / "b" / "deep.txt").write_text("d" * 4096, encoding="utf-8")
    (base / "top.txt").write_text("t", encoding="utf-8")
    return base


def test_parse_mountinfo_lists_mount_points_and_decodes_escapes() -> None:
    assert parse_mountinfo(text=MOUNTINFO) == frozenset({"/mnt2", "/home/u/with space"})


def test_remove_directory_removes_everything_and_counts_what_it_freed(tmp_path: Path) -> None:
    base = tree(base=tmp_path / "t")

    removal = remove_directory(fingerprint=fingerprint_of(path=base))

    assert removal.root_removed and removal.remaining == 0
    assert removal.removed == 4
    assert removal.freed_bytes >= 4096
    assert not base.exists()


def test_a_subfolder_on_another_device_is_skipped_and_survives(tmp_path: Path) -> None:
    base = tree(base=tmp_path / "t")
    fingerprint = fingerprint_of(path=base)
    foreign = fingerprint.st_dev + 1

    removal = empty_directory(fingerprint=fingerprint, root_dev=foreign)

    assert removal.skipped_mounts == (f"{base}/a",)
    assert (base / "a" / "b" / "deep.txt").exists()
    assert not (base / "top.txt").exists()

    again = empty_directory(fingerprint=fingerprint)
    assert again.skipped_mounts == () and not (base / "a").exists()


def test_a_listed_mount_point_is_skipped_even_on_the_same_device(tmp_path: Path) -> None:
    base = tree(base=tmp_path / "t")

    removal = empty_directory(
        fingerprint=fingerprint_of(path=base), mountpoints=frozenset({f"{base}/a/b"})
    )

    assert removal.skipped_mounts == (f"{base}/a/b",)
    assert (base / "a" / "b" / "deep.txt").exists()


def test_a_folder_replaced_by_another_inode_is_refused(tmp_path: Path) -> None:
    base = tree(base=tmp_path / "t")
    real = fingerprint_of(path=base)
    forged = DirFingerprint(realpath=real.realpath, st_ino=real.st_ino + 1, st_dev=real.st_dev)

    with pytest.raises(TargetChanged):
        empty_directory(fingerprint=forged)
    assert (base / "top.txt").exists()
    assert empty_directory(fingerprint=real).removed > 0


def test_a_root_that_is_a_symlink_is_not_followed(tmp_path: Path) -> None:
    victim = tree(base=tmp_path / "victim")
    link = tmp_path / "link"
    link.symlink_to(victim)
    real = fingerprint_of(path=victim)
    via_link = DirFingerprint(realpath=str(link), st_ino=real.st_ino, st_dev=real.st_dev)

    with pytest.raises(OSError):
        empty_directory(fingerprint=via_link)
    assert (victim / "top.txt").exists()


def test_the_real_runner_reports_a_missing_tool_and_a_timeout() -> None:
    runner = SubprocessRunner()

    with pytest.raises(ControlFailed, match="not found"):
        runner.run(argv=["wimm-no-such-tool-xyz"], timeout_s=5)
    with pytest.raises(ControlFailed, match="did not finish"):
        runner.run(argv=[sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.3)

    ok = runner.run(argv=[sys.executable, "-c", "print('hello')"], timeout_s=30)
    assert (ok.returncode, ok.output) == (0, "hello")
    bad = runner.run(argv=[sys.executable, "-c", "import sys; sys.exit(3)"], timeout_s=30)
    assert bad.returncode == 3


def test_cwds_of_the_user_include_the_current_one_and_other_users_do_not() -> None:
    mine = PsutilCwds(owner_uid=os.getuid()).cwds()
    assert Path.cwd() in mine
    assert Path.cwd() not in PsutilCwds(owner_uid=os.getuid() + 12345).cwds()


# --- the removal root itself can be a mount (T-5.3c review) ------------------------


def test_remove_directory_refuses_a_root_listed_as_a_mount_point(tmp_path: Path) -> None:
    base = tree(base=tmp_path / "t")
    fingerprint = fingerprint_of(path=base)

    with pytest.raises(TargetChanged, match="mount"):
        remove_directory(fingerprint=fingerprint, mountpoints=frozenset({str(base)}))

    assert (base / "a" / "b" / "deep.txt").exists() and (base / "top.txt").exists()
    assert remove_directory(fingerprint=fingerprint).root_removed


def test_remove_directory_refuses_a_root_on_another_device_than_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tree(base=tmp_path / "t")
    fingerprint = fingerprint_of(path=base)
    with monkeypatch.context() as patch:
        patch.setattr(safe_tree, "_device_of", lambda *, fd: fingerprint.st_dev + 1)
        with pytest.raises(TargetChanged, match="mount"):
            remove_directory(fingerprint=fingerprint)

    assert (base / "a" / "b" / "deep.txt").exists() and (base / "top.txt").exists()
    assert remove_directory(fingerprint=fingerprint).root_removed


def test_empty_directory_refuses_a_root_listed_as_a_mount_point(tmp_path: Path) -> None:
    base = tree(base=tmp_path / "t")
    fingerprint = fingerprint_of(path=base)

    with pytest.raises(TargetChanged, match="mount"):
        empty_directory(fingerprint=fingerprint, mountpoints=frozenset({str(base)}))

    assert (base / "a" / "b" / "deep.txt").exists() and (base / "top.txt").exists()
    assert empty_directory(fingerprint=fingerprint).remaining == 0
    assert list(base.iterdir()) == []


def test_empty_directory_refuses_a_root_on_another_device_than_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tree(base=tmp_path / "t")
    fingerprint = fingerprint_of(path=base)
    with monkeypatch.context() as patch:
        patch.setattr(safe_tree, "_device_of", lambda *, fd: fingerprint.st_dev + 1)
        with pytest.raises(TargetChanged, match="mount"):
            empty_directory(fingerprint=fingerprint)

    assert (base / "a" / "b" / "deep.txt").exists() and (base / "top.txt").exists()
    assert empty_directory(fingerprint=fingerprint).remaining == 0


def _trash_like(*, base: Path) -> Path:
    for name in ("files", "info"):
        (base / name).mkdir(parents=True)
        (base / name / "x.txt").write_text("x" * 4096, encoding="utf-8")
    return base


def test_a_trash_child_listed_as_a_mount_is_skipped_and_its_content_survives(
    tmp_path: Path,
) -> None:
    base = _trash_like(base=tmp_path / "trash")
    fingerprint = fingerprint_of(path=base)

    removal = empty_directory(
        fingerprint=fingerprint,
        subdirs=("files", "info"),
        mountpoints=frozenset({f"{base}/files"}),
    )

    assert removal.skipped_mounts == (f"{base}/files",)
    assert (base / "files" / "x.txt").exists()
    assert list((base / "info").iterdir()) == []


def test_a_trash_child_on_another_device_is_skipped_and_its_content_survives(
    tmp_path: Path,
) -> None:
    base = _trash_like(base=tmp_path / "trash")
    fingerprint = fingerprint_of(path=base)

    removal = empty_directory(
        fingerprint=fingerprint, subdirs=("files", "info"), root_dev=fingerprint.st_dev + 1
    )

    assert set(removal.skipped_mounts) == {f"{base}/files", f"{base}/info"}
    assert (base / "files" / "x.txt").exists() and (base / "info" / "x.txt").exists()

    again = empty_directory(fingerprint=fingerprint, subdirs=("files", "info"))
    assert again.skipped_mounts == ()
    assert list((base / "files").iterdir()) == [] and list((base / "info").iterdir()) == []


def test_the_real_runner_runs_in_the_root_not_in_the_service_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # npm, pip and uv read config files from the working directory (.npmrc, uv.toml).
    monkeypatch.chdir(tmp_path)
    shown = SubprocessRunner().run(
        argv=[sys.executable, "-c", "import os; print(os.getcwd())"], timeout_s=30
    )
    assert shown.output == "/"
    assert Path.cwd() == tmp_path


def test_removal_starts_at_the_folder_whatever_the_device_of_its_root(tmp_path: Path) -> None:
    """The root of a plan may sit on another disk (ADR-007): the removal never looks at it.

    It starts from the folder's own fingerprint and stops at the mount points inside it.
    """
    base = tree(base=tmp_path / "root" / "proj" / "node_modules")
    (base / "mnt" / "disk").mkdir(parents=True)
    (base / "mnt" / "disk" / "keep.txt").write_text("k", encoding="utf-8")
    fingerprint = fingerprint_of(path=base)

    removal = remove_directory(fingerprint=fingerprint, mountpoints=frozenset({f"{base}/mnt/disk"}))

    assert removal.skipped_mounts == (f"{base}/mnt/disk",)
    assert (base / "mnt" / "disk" / "keep.txt").exists()
    assert not (base / "a").exists() and not (base / "top.txt").exists()
    assert not removal.root_removed and removal.remaining > 0
