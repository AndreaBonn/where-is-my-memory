import os
from pathlib import Path

import pytest

from wimm.model.actions import DirFingerprint
from wimm.service import executor_disk_fs


def _fingerprint(path: Path) -> DirFingerprint:
    info = os.lstat(path)
    return DirFingerprint(realpath=str(path), st_ino=info.st_ino, st_dev=info.st_dev)


def test_guard_stops_a_removal_aimed_outside_the_tmpdir(
    tmp_path: Path, guard_removals: list[str], tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("decoy")
    (outside / "keep.txt").write_text("x")
    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "drop.txt").write_text("x")
    # The guarded entry point, the name the executor calls; the module does not re-export it.
    empty = vars(executor_disk_fs)["empty_directory"]

    empty(fingerprint=_fingerprint(inside), mountpoints=frozenset())
    with pytest.raises(AssertionError, match="outside the tmpdir"):
        empty(fingerprint=_fingerprint(outside), mountpoints=frozenset())

    assert guard_removals == [str(outside)]
    assert (outside / "keep.txt").exists()
    assert not (inside / "drop.txt").exists()
    guard_removals.clear()
