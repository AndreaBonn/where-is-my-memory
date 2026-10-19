import errno
import os
from pathlib import Path

import pytest

from wimm.collectors.cache_items import list_tree
from wimm.collectors.dirsize import measure_dir_size
from wimm.core.constants import DIRSIZE_PAUSE_EVERY, DIRSIZE_PAUSE_S, DIRSIZE_YIELD_EVERY


def _noop(_seconds: float) -> None:
    return None


def test_list_tree_disk_bytes_equals_measure_dir_size_on_the_same_tree(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f.bin").write_bytes(b"x" * 9000)
    (root / "a" / "g.bin").write_bytes(b"y" * 5000)
    os.link(root / "a" / "g.bin", root / "a" / "b" / "g2.bin")
    (root / "a" / "link").symlink_to("b/f.bin")
    (root / "dirlink").symlink_to(tmp_path)
    expected = measure_dir_size(root=root, cache_dir=tmp_path / "sizes", sleep=_noop)
    listing = list_tree(root=root, sleep=_noop)
    assert expected.size_bytes > 0
    assert listing.disk_bytes == expected.size_bytes


def test_list_tree_never_gives_a_directory_a_size_of_its_own(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "d").mkdir(parents=True)
    (root / "d" / "f").write_bytes(b"1" * 100)
    listing = list_tree(root=root, sleep=_noop)
    assert [e.size for e in listing.entries if e.path == "d"] == [0]
    assert listing.disk_bytes > sum(e.size for e in listing.entries)


def _many_files(root: Path, count: int) -> None:
    root.mkdir()
    for number in range(count):
        (root / f"f{number:05d}").write_bytes(b"")


def test_list_tree_yields_and_pauses_at_the_dirsize_cadence(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    _many_files(root, 10_000)
    calls: list[float] = []
    list_tree(root=root, sleep=calls.append)
    assert calls.count(DIRSIZE_PAUSE_S) == 1
    assert calls.count(0) == DIRSIZE_PAUSE_EVERY // DIRSIZE_YIELD_EVERY - 1


def test_list_tree_does_not_sleep_on_a_small_tree(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    _many_files(root, 50)
    calls: list[float] = []
    list_tree(root=root, sleep=calls.append)
    assert calls == []


class _Cancelled(Exception):
    pass


def test_list_tree_propagates_an_exception_raised_by_sleep(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    _many_files(root, 2500)
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)
        raise _Cancelled

    with pytest.raises(_Cancelled):
        list_tree(root=root, sleep=sleep)
    assert calls == [0]


def test_list_tree_does_not_follow_a_dir_swapped_for_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"s" * 8192)
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "inner.bin").write_bytes(b"i" * 4096)
    swapped: list[bool] = []

    def swap() -> None:
        if not swapped:
            swapped.append(True)
            os.rename(root / "sub", root / "moved")
            os.symlink(outside, root / "sub")

    real_scandir, real_open = os.scandir, os.open

    def scandir(path: object) -> object:
        if isinstance(path, str) and path.endswith("/sub"):
            swap()
        return real_scandir(path)  # type: ignore[call-overload]

    def opener(path: str, flags: int, *args: object, **kwargs: object) -> int:
        if path == "sub":
            swap()
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "open", opener)
    paths = {entry.path for entry in list_tree(root=root, sleep=_noop).entries}
    assert swapped == [True]
    assert "sub" in paths
    assert not any(path.startswith("sub/") for path in paths)


def test_list_tree_closes_every_directory_descriptor(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f").write_bytes(b"1")
    before = len(os.listdir("/proc/self/fd"))
    list_tree(root=root, sleep=_noop)
    assert len(os.listdir("/proc/self/fd")) == before


def test_list_tree_warns_when_out_of_file_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Running out of descriptors hides a whole subtree: that must not look like a routine skip.
    root = tmp_path / "tree"
    (root / "deep").mkdir(parents=True)
    real_open = os.open

    def exhausted(path: str, flags: int, *args: object, **kwargs: object) -> int:
        if path == "deep":
            raise OSError(errno.EMFILE, "Too many open files")
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", exhausted)
    with caplog.at_level("INFO"):
        list_tree(root=root, sleep=_noop)
    levels = [r.levelname for r in caplog.records if "deep" in r.getMessage()]
    assert levels == ["WARNING"]
