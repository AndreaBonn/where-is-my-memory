import json
import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from wimm.collectors import dirsize
from wimm.collectors.dirsize import DirSize, measure_dir_size
from wimm.core.constants import DISK_CACHE_FILENAME

REAL_SCANDIR = os.scandir


def _blocks(*paths: Path) -> int:
    return sum(os.lstat(path).st_blocks * 512 for path in paths)


def _measure(root: Path, cache_dir: Path) -> DirSize:
    return measure_dir_size(root=root, cache_dir=cache_dir, sleep=lambda _seconds: None)


class _VanishedEntry:
    """A directory entry whose file is gone by the time it is stat-ed."""

    def __init__(self, entry: os.DirEntry[str]) -> None:
        self.path = entry.path

    def is_symlink(self) -> bool:
        return False

    def stat(self, *, follow_symlinks: bool) -> os.stat_result:
        raise FileNotFoundError(self.path)


class _FailingScan:
    """Iterator over a real directory that rewrites entries and can fail mid-way."""

    def __init__(
        self,
        directory: Path,
        *,
        rewrite: Callable[[os.DirEntry[str]], Any] = lambda entry: entry,
        fail_after: int | None = None,
    ) -> None:
        self._inner = REAL_SCANDIR(directory)
        self._rewrite = rewrite
        self._left = fail_after

    def __enter__(self) -> "_FailingScan":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._inner.close()

    def __iter__(self) -> Iterator[Any]:
        return self

    def __next__(self) -> Any:
        if self._left == 0:
            raise PermissionError("input/output error")
        if self._left is not None:
            self._left -= 1
        return self._rewrite(next(self._inner))


def _scandir_for(*, target: Path, monkeypatch: pytest.MonkeyPatch, **options: Any) -> None:
    def fake(path: Any) -> Any:
        if Path(path) == target:
            return _FailingScan(Path(path), **options)
        return REAL_SCANDIR(path)

    monkeypatch.setattr(target=os, name="scandir", value=fake)


def test_root_that_cannot_be_stat_ed_by_the_scan_counts_one_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    real_lstat = os.lstat
    state = {"seen": 0, "fail_at": 0}

    def lstat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if str(path) == str(root):
            state["seen"] += 1
            if state["seen"] == state["fail_at"]:
                raise PermissionError("denied")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(target=os, name="lstat", value=lstat)
    healthy = _measure(root, tmp_path / "healthy")
    # In a healthy run the scan is the last one to stat the root: make that call fail.
    state.update(seen=0, fail_at=state["seen"])

    result = _measure(root, tmp_path / "failing")

    assert healthy.error_count == 0
    assert healthy.size_bytes > 0
    assert (result.size_bytes, result.error_count) == (0, 1)
    assert not (tmp_path / "failing" / DISK_CACHE_FILENAME).exists()


def test_subdirectory_that_cannot_be_listed_is_counted_and_the_rest_measured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    broken = root / "broken"
    broken.mkdir(parents=True)
    visible = root / "visible.bin"
    visible.write_bytes(b"y" * 4096)

    def refuse(path: Any) -> Any:
        if Path(path) == broken:
            raise PermissionError("denied")
        return REAL_SCANDIR(path)

    monkeypatch.setattr(target=os, name="scandir", value=refuse)

    result = _measure(root, tmp_path / "sizes")

    assert result.size_bytes == _blocks(root, broken, visible)
    assert result.error_count == 1


def test_listing_that_fails_midway_keeps_what_was_read_and_counts_one_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    for name in ("a.bin", "b.bin", "c.bin"):
        (root / name).write_bytes(b"x" * 4096)
    _scandir_for(target=root, monkeypatch=monkeypatch, fail_after=1)

    result = _measure(root, tmp_path / "sizes")

    # Exactly one entry was delivered before the failure: root itself plus that one file.
    assert result.error_count == 1
    assert result.size_bytes == _blocks(root, root / "a.bin")  # all three files weigh the same


def test_entry_that_vanishes_before_stat_is_counted_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    gone = root / "gone.bin"
    kept = root / "kept.bin"
    gone.write_bytes(b"x" * 8192)
    kept.write_bytes(b"y" * 4096)
    _scandir_for(
        target=root,
        monkeypatch=monkeypatch,
        rewrite=lambda entry: _VanishedEntry(entry) if entry.name == "gone.bin" else entry,
    )

    result = _measure(root, tmp_path / "sizes")

    assert result.error_count == 1
    assert result.size_bytes == _blocks(root, kept)
    assert not (tmp_path / "sizes" / DISK_CACHE_FILENAME).exists()


def test_cache_path_that_cannot_be_read_or_written_still_gives_the_size(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    cache_dir = tmp_path / "sizes"
    (cache_dir / DISK_CACHE_FILENAME).mkdir(parents=True)  # a folder where the file belongs

    with caplog.at_level(logging.WARNING, logger=dirsize.LOGGER.name):
        result = _measure(root, cache_dir)

    assert result.size_bytes == _blocks(root, root / "f.bin")
    assert result.error_count == 0
    messages = [record.getMessage() for record in caplog.records]
    assert any(text.startswith("Cannot read size cache") for text in messages)
    assert any(text.startswith("Cannot write size cache") for text in messages)


def test_cache_from_another_version_is_ignored_and_rewritten(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    cache_dir = tmp_path / "sizes"
    cache_dir.mkdir()
    cache_file = cache_dir / DISK_CACHE_FILENAME
    cache_file.write_text(json.dumps({"version": 999, "entries": {"k": {}}}))

    with caplog.at_level(logging.WARNING, logger=dirsize.LOGGER.name):
        result = _measure(root, cache_dir)

    assert result.from_cache is False
    assert result.size_bytes == _blocks(root, root / "f.bin")
    assert any("Ignoring corrupt size cache" in r.getMessage() for r in caplog.records)
    rewritten = json.loads(cache_file.read_text())
    assert rewritten["version"] != 999
    assert "k" not in rewritten["entries"]


@pytest.mark.parametrize("field", ["size", "errors"])
def test_cache_entry_with_a_non_integer_field_is_rescanned(tmp_path: Path, field: str) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "f.bin").write_bytes(b"x" * 5000)
    cache_dir = tmp_path / "sizes"
    expected = _measure(root, cache_dir).size_bytes
    assert _measure(root, cache_dir).from_cache is True
    cache_file = cache_dir / DISK_CACHE_FILENAME
    document = json.loads(cache_file.read_text())
    (key,) = document["entries"]
    document["entries"][key][field] = "12"
    cache_file.write_text(json.dumps(document))

    rescanned = _measure(root, cache_dir)

    assert rescanned.from_cache is False
    assert rescanned.size_bytes == expected
