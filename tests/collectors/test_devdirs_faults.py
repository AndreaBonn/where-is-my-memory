import os
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from wimm.collectors import devdirs
from wimm.collectors.devdirs import (
    DevDirSettings,
    _build_devdir,
    _Walker,
    project_age_days,
    scan_devdirs,
)

NOW = 1_800_000_000.0
DAY = 86400
REAL_SCANDIR = os.scandir


def _age(path: Path, days: float) -> None:
    stamp = NOW - days * DAY
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _project(root: Path, name: str) -> Path:
    project = root / name
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "dep.js").write_bytes(b"x" * 5000)
    (project / "setup.py").write_text("x")
    _age(project / "setup.py", 100)
    return project


def _scan(root: Path, tmp_path: Path, sleeps: list[float] | None = None) -> devdirs.DevDirScan:
    record = sleeps if sleeps is not None else []
    settings = DevDirSettings(roots=(root,), home=tmp_path, max_depth=6)
    return scan_devdirs(
        settings=settings, cache_dir=tmp_path / "sizes", now=NOW, sleep=record.append
    )


class _BrokenEntry:
    """A directory entry that fails on the call named by ``broken``."""

    def __init__(self, entry: os.DirEntry[str], broken: str) -> None:
        self.name, self.path, self._entry, self._broken = entry.name, entry.path, entry, broken

    def is_dir(self, *, follow_symlinks: bool) -> bool:
        if self._broken == "is_dir":
            raise PermissionError("denied")
        return self._entry.is_dir(follow_symlinks=follow_symlinks)

    def stat(self, *, follow_symlinks: bool) -> os.stat_result:
        if self._broken == "stat":
            raise FileNotFoundError(self.path)
        return self._entry.stat(follow_symlinks=follow_symlinks)


class _Listing:
    """A real directory listing that can rewrite entries or fail after some of them."""

    def __init__(
        self,
        directory: Path,
        *,
        rewrite: Callable[[os.DirEntry[str]], Any],
        fail_after: int | None,
    ) -> None:
        self._inner = REAL_SCANDIR(directory)
        self._rewrite, self._left = rewrite, fail_after

    def __enter__(self) -> "_Listing":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._inner.close()

    def __iter__(self) -> "_Listing":
        return self

    def __next__(self) -> Any:
        if self._left == 0:
            raise PermissionError("input/output error")
        if self._left is not None:
            self._left -= 1
        return self._rewrite(next(self._inner))


def _break_listing(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    *,
    rewrite: Callable[[os.DirEntry[str]], Any] = lambda entry: entry,
    fail_after: int | None = None,
) -> None:
    def fake(path: Any) -> Any:
        if Path(path) == directory:
            return _Listing(Path(path), rewrite=rewrite, fail_after=fail_after)
        return REAL_SCANDIR(path)

    monkeypatch.setattr(target=os, name="scandir", value=fake)


def test_scan_pauses_every_n_entries_and_not_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(target=devdirs, name="DIRSIZE_PAUSE_EVERY", value=5)
    root = tmp_path / "work"
    root.mkdir()
    for index in range(4):
        (root / f"d{index}").mkdir()
    short: list[float] = []
    _scan(root, tmp_path, sleeps=short)
    for index in range(4, 12):
        (root / f"d{index}").mkdir()
    long: list[float] = []

    _scan(root, tmp_path, sleeps=long)

    assert short == []
    assert long == [0.01, 0.01]  # 12 entries in the root: after the 5th and the 10th


def test_scan_a_folder_whose_context_cannot_be_read_is_counted_and_not_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "work"
    app = _project(root, "app")
    assert [item.path for item in _scan(root, tmp_path).devdirs] == [str(app / "node_modules")]

    def refuse(*, path: Path, home: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(target=devdirs, name="read_devdir_context", value=refuse)
    result = _scan(root, tmp_path)

    assert result.devdirs == ()
    assert result.error_count == 1


def test_scan_entry_that_cannot_be_typed_is_counted_and_the_others_are_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "work"
    app = _project(root, "app")
    (root / "odd").mkdir()
    _break_listing(
        monkeypatch,
        root,
        rewrite=lambda entry: _BrokenEntry(entry, "is_dir") if entry.name == "odd" else entry,
    )

    result = _scan(root, tmp_path)

    assert result.error_count == 1
    assert [item.path for item in result.devdirs] == [str(app / "node_modules")]


def test_scan_listing_that_fails_midway_counts_one_error_and_keeps_what_it_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "work"
    app = _project(root, "app")
    _break_listing(monkeypatch, root, fail_after=1)  # `app` is the only entry, then the failure

    result = _scan(root, tmp_path)

    assert result.error_count == 1
    assert [item.path for item in result.devdirs] == [str(app / "node_modules")]


def test_project_age_is_unknown_when_its_listing_fails_midway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _project(tmp_path / "work", "app")
    assert project_age_days(project=app, now=NOW) == 100
    _break_listing(monkeypatch, app, fail_after=1)

    assert project_age_days(project=app, now=NOW) is None


def test_project_age_is_unknown_when_an_entry_cannot_be_stat_ed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _project(tmp_path / "work", "app")
    _break_listing(
        monkeypatch,
        app,
        rewrite=lambda entry: _BrokenEntry(entry, "stat") if entry.name == "setup.py" else entry,
    )

    assert project_age_days(project=app, now=NOW) is None


def test_project_age_of_a_project_that_does_not_exist_is_unknown(tmp_path: Path) -> None:
    app = _project(tmp_path / "work", "app")
    assert project_age_days(project=app, now=NOW) == 100

    assert project_age_days(project=tmp_path / "work" / "gone", now=NOW) is None


def test_a_folder_that_vanished_since_the_walk_is_dropped_and_counted(tmp_path: Path) -> None:
    app = _project(tmp_path / "work", "app")
    walker = _Walker(max_depth=6, sleep=lambda _s: None, home=tmp_path)
    present = _build_devdir(path=app / "node_modules", walker=walker, cache_dir=tmp_path, now=NOW)
    assert present is not None
    assert walker.errors == 0

    gone = _build_devdir(path=app / "vanished", walker=walker, cache_dir=tmp_path, now=NOW)

    assert gone is None
    assert walker.errors == 1
