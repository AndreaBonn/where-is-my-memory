import json
import logging
import os
from pathlib import Path

import pytest

from wimm.collectors import dirsize
from wimm.collectors.dirsize import DirSize, measure_dir_size
from wimm.core.constants import DIRSIZE_PAUSE_S, DISK_CACHE_FILENAME


def _blocks(*paths: Path) -> int:
    return sum(os.lstat(path).st_blocks * 512 for path in paths)


def _measure(root: Path, cache_dir: Path, sleeps: list[float] | None = None) -> DirSize:
    record = sleeps if sleeps is not None else []
    return measure_dir_size(root=root, cache_dir=cache_dir, sleep=record.append)


def test_nested_files_exact_blocks(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "a" / "b").mkdir(parents=True)
    first = root / "one.bin"
    second = root / "a" / "b" / "two.bin"
    first.write_bytes(b"x" * 5000)
    second.write_bytes(b"y" * 9000)
    expected = _blocks(root, root / "a", root / "a" / "b", first, second)
    result = _measure(root, tmp_path / "sizes")
    assert result.size_bytes == expected
    assert result.error_count == 0
    assert result.from_cache is False


def test_symlinks_not_followed_or_counted(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"z" * 100000)
    root = tmp_path / "tree"
    root.mkdir()
    real = root / "real.bin"
    real.write_bytes(b"x" * 4000)
    (root / "link_file").symlink_to(outside / "big.bin")
    (root / "link_dir").symlink_to(outside, target_is_directory=True)
    result = _measure(root, tmp_path / "sizes")
    assert result.size_bytes == _blocks(root, real)
    assert result.size_bytes < 100000


def test_hard_link_counted_once(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    original = root / "orig.bin"
    original.write_bytes(b"x" * 8192)
    os.link(src=original, dst=root / "alias.bin")
    result = _measure(root, tmp_path / "sizes")
    assert result.size_bytes == _blocks(root, original)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_directory_skipped_and_counted(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    locked = root / "locked"
    locked.mkdir(parents=True)
    (locked / "hidden.bin").write_bytes(b"x" * 8192)
    visible = root / "visible.bin"
    visible.write_bytes(b"y" * 4096)
    expected = _blocks(root, locked, visible)
    locked.chmod(0o000)
    try:
        result = _measure(root, tmp_path / "sizes")
    finally:
        locked.chmod(0o700)
    assert result.size_bytes == expected
    assert result.error_count == 1


def test_missing_root_reports_error_without_raising(tmp_path: Path) -> None:
    result = _measure(tmp_path / "absent", tmp_path / "sizes")
    assert result.size_bytes == 0
    assert result.error_count == 1


def test_second_call_uses_cache_without_scanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    cache_dir = tmp_path / "sizes"
    first = _measure(root, cache_dir)
    calls: list[object] = []
    real_scandir = os.scandir

    def counting_scandir(path: Path) -> object:
        calls.append(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", counting_scandir)
    second = _measure(root, cache_dir)
    assert calls == []
    assert second.from_cache is True
    assert second.size_bytes == first.size_bytes
    cache_file = cache_dir / DISK_CACHE_FILENAME
    assert cache_file.stat().st_mode & 0o777 == 0o600


def test_root_mtime_change_invalidates_cache(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    cache_dir = tmp_path / "sizes"
    first = _measure(root, cache_dir)
    added = root / "g.bin"
    added.write_bytes(b"y" * 9000)
    second = _measure(root, cache_dir)
    assert second.from_cache is False
    assert second.size_bytes == first.size_bytes + _blocks(added)


def test_truncated_cache_recomputed_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    cache_dir = tmp_path / "sizes"
    first = _measure(root, cache_dir)
    cache_file = cache_dir / DISK_CACHE_FILENAME
    cache_file.write_bytes(cache_file.read_bytes()[:10])
    with caplog.at_level(logging.WARNING, logger=dirsize.LOGGER.name):
        second = _measure(root, cache_dir)
    assert second.from_cache is False
    assert second.size_bytes == first.size_bytes
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert json.loads(cache_file.read_text())["entries"]


def test_wrong_shape_cache_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    cache_dir = tmp_path / "sizes"
    cache_dir.mkdir()
    (cache_dir / DISK_CACHE_FILENAME).write_text('["not", "a", "dict"]')
    with caplog.at_level(logging.WARNING, logger=dirsize.LOGGER.name):
        result = _measure(root, cache_dir)
    assert result.from_cache is False
    assert result.size_bytes == _blocks(root)
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert json.loads((cache_dir / DISK_CACHE_FILENAME).read_text())["entries"]


def test_yields_gil_and_pauses_at_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dirsize, "DIRSIZE_YIELD_EVERY", 5)
    monkeypatch.setattr(dirsize, "DIRSIZE_PAUSE_EVERY", 10)
    root = tmp_path / "tree"
    root.mkdir()
    for index in range(25):
        (root / f"f{index}").write_bytes(b"x")
    sleeps: list[float] = []
    _measure(root, tmp_path / "sizes", sleeps)
    assert sleeps.count(0) == 3
    assert sleeps.count(DIRSIZE_PAUSE_S) == 2


def test_symlinked_root_sees_changes_in_its_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    cache_dir = tmp_path / "sizes"
    empty = _measure(link, cache_dir)
    (target / "big.bin").write_bytes(b"x" * 100000)
    grown = _measure(link, cache_dir)
    assert empty.size_bytes == _blocks(target)
    assert grown.from_cache is False
    assert grown.size_bytes == _blocks(target, target / "big.bin")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_result_with_errors_is_not_cached(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    locked = root / "locked"
    locked.mkdir(parents=True)
    cache_dir = tmp_path / "sizes"
    locked.chmod(0)
    try:
        failed = _measure(root, cache_dir)
    finally:
        locked.chmod(0o700)
    assert not (cache_dir / DISK_CACHE_FILENAME).exists()
    retried = _measure(root, cache_dir)
    assert failed.error_count == 1
    assert retried.from_cache is False
    assert retried.error_count == 0
    assert _measure(root, cache_dir).from_cache is True
