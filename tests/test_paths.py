import os
import stat
from pathlib import Path

import pytest

from wimm.paths import default_user_paths, ensure_private_dir, write_private_atomic


def test_paths_are_frozen_and_glib_defaults_are_stable() -> None:
    paths = default_user_paths()
    assert paths == default_user_paths()
    assert paths.config_dir.name == "where-is-my-memory"
    assert paths.state_dir.name == paths.cache_dir.name == paths.config_dir.name
    for name in ("config_dir", "state_dir", "cache_dir"):
        with pytest.raises(AttributeError):
            setattr(paths, name, Path("other"))


def test_private_modes_override_umask(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    previous = os.umask(0o777)
    try:
        ensure_private_dir(path=directory)
        write_private_atomic(path=directory / "data", data=b"complete")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / "data").stat().st_mode) == 0o600
    assert (directory / "data").read_bytes() == b"complete"


def test_private_dir_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o755)
    link = tmp_path / "link"
    link.symlink_to(target=target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        ensure_private_dir(path=link)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_atomic_failure_preserves_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "atomic"
    write_private_atomic(path=path, data=b"original")

    def fail_replace(src: object, dst: object) -> None:
        raise OSError("replacement failed")

    monkeypatch.setattr(target=os, name="replace", value=fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        write_private_atomic(path=path, data=b"replacement")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.glob(pattern=".atomic.*")) == []


def test_atomic_fsync_failure_removes_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_sync(fd: int) -> None:
        raise OSError("sync failed")

    monkeypatch.setattr(target=os, name="fsync", value=fail_sync)
    with pytest.raises(OSError, match="sync failed"):
        write_private_atomic(path=tmp_path / "atomic", data=b"partial")
    assert not (tmp_path / "atomic").exists()
    assert list(tmp_path.glob(pattern=".atomic.*")) == []
    monkeypatch.undo()
    write_private_atomic(path=tmp_path / "atomic", data=b"complete")
    assert (tmp_path / "atomic").read_bytes() == b"complete"


def test_atomic_syncs_file_then_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[bool, bytes]] = []
    path = tmp_path / "atomic"

    def record_sync(fd: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        events.append((is_directory, path.read_bytes() if is_directory else b""))

    monkeypatch.setattr(target=os, name="fsync", value=record_sync)
    write_private_atomic(path=path, data=b"complete")
    assert events == [(False, b""), (True, b"complete")]


def test_fdopen_failure_closes_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    descriptors: list[int] = []

    def fail_fdopen(fd: int, mode: str) -> None:
        descriptors.append(fd)
        raise OSError("fdopen failed")

    monkeypatch.setattr(target=os, name="fdopen", value=fail_fdopen)
    with pytest.raises(OSError, match="fdopen failed"):
        write_private_atomic(path=tmp_path / "atomic", data=b"complete")
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert list(tmp_path.glob(pattern=".atomic.*")) == []
    monkeypatch.undo()
    write_private_atomic(path=tmp_path / "atomic", data=b"complete")
    assert (tmp_path / "atomic").read_bytes() == b"complete"


def test_parent_symlinks_are_allowed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target=target, target_is_directory=True)
    ensure_private_dir(path=link / "private")
    write_private_atomic(path=link / "private/data", data=b"complete")
    assert (target / "private/data").read_bytes() == b"complete"


def test_private_directory_chmod_does_not_follow_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o755)
    directory = tmp_path / "private"
    original_makedirs = os.makedirs

    def race_makedirs(name: Path, mode: int, exist_ok: bool) -> None:
        original_makedirs(name=name, mode=mode, exist_ok=exist_ok)
        directory.rmdir()
        directory.symlink_to(target=target, target_is_directory=True)

    monkeypatch.setattr(target=os, name="makedirs", value=race_makedirs)
    with pytest.raises((OSError, NotImplementedError)):
        ensure_private_dir(path=directory)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
