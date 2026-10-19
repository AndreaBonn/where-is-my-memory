import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.collectors.devdirs_helpers import NOW, _age, _paths, _project, _scan, _venv
from wimm.collectors.devdirs import DevDirSettings, project_age_days, scan_devdirs
from wimm.core.constants import DIRSIZE_YIELD_EVERY


@pytest.fixture
def locked_dir(tmp_path: Path) -> Iterator[Path]:
    locked = tmp_path / "work" / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0)
    try:
        yield locked
    finally:
        locked.chmod(stat.S_IRWXU)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_scan_unreadable_directory_counted_not_raised(tmp_path: Path, locked_dir: Path) -> None:
    root = tmp_path / "work"
    ok = _project(root, "ok")
    result = _scan(root, tmp_path)
    assert result.error_count == 1
    assert _paths(result) == {str(ok / "node_modules")}


def test_scan_readable_tree_has_zero_errors(tmp_path: Path) -> None:
    root = tmp_path / "work"
    _project(root, "ok")
    assert _scan(root, tmp_path).error_count == 0


def test_scan_yields_gil_on_large_directories(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    for index in range(DIRSIZE_YIELD_EVERY + 1):
        (root / f"f{index}").write_bytes(b"")
    sleeps: list[float] = []
    _scan(root, tmp_path, sleeps=sleeps)
    assert sleeps == [0]


def test_scan_small_tree_does_not_sleep(tmp_path: Path) -> None:
    root = tmp_path / "work"
    _project(root, "app")
    sleeps: list[float] = []
    _scan(root, tmp_path, sleeps=sleeps)
    assert sleeps == []


def test_scan_nested_roots_report_each_folder_once(tmp_path: Path) -> None:
    root = tmp_path / "work"
    web = _project(root, "web")
    settings = DevDirSettings(roots=(root, web, root), home=tmp_path, max_depth=6)
    result = scan_devdirs(settings=settings, cache_dir=tmp_path / "sizes", now=NOW, sleep=print)
    assert [item.path for item in result.devdirs] == [str(web / "node_modules")]


def test_scan_age_ignores_a_sibling_dependency_folder(tmp_path: Path) -> None:
    web = _project(tmp_path / "work", "web", age=200)
    _venv(web / ".venv")
    _age(web / "node_modules", 0)
    result = _scan(tmp_path / "work", tmp_path)
    assert {item.age_days for item in result.devdirs} == {200}
    assert len(result.devdirs) == 2


def test_scan_age_ignores_a_symlinked_src(tmp_path: Path) -> None:
    fresh = tmp_path / "elsewhere"
    fresh.mkdir()
    (fresh / "new.py").write_text("x")
    web = _project(tmp_path / "work", "web", age=200)
    (web / "src").symlink_to(fresh)
    # The link itself is a first-level entry: only the target's newer file must not count.
    _age(web / "src", 200)
    result = _scan(tmp_path / "work", tmp_path)
    assert [item.age_days for item in result.devdirs] == [200]
    assert result.error_count == 0


def test_scan_src_that_is_a_file_is_not_an_error(tmp_path: Path) -> None:
    web = _project(tmp_path / "work", "web", age=200)
    (web / "src").write_text("x")
    _age(web / "src", 150)
    result = _scan(tmp_path / "work", tmp_path)
    assert [item.age_days for item in result.devdirs] == [150]
    assert result.error_count == 0


def test_folder_replaced_by_a_symlink_before_measuring_is_dropped(tmp_path: Path) -> None:
    from wimm.collectors.devdirs import _build_devdir, _Walker

    web = _project(tmp_path / "work", "web")
    real = _build_devdir(
        path=web / "node_modules",
        walker=_Walker(max_depth=6, sleep=print, home=tmp_path),
        cache_dir=tmp_path,
        now=NOW,
    )
    (web / "node_modules").rename(tmp_path / "moved")
    (web / "node_modules").symlink_to(tmp_path / "moved")
    swapped = _build_devdir(
        path=web / "node_modules",
        walker=_Walker(max_depth=6, sleep=print, home=tmp_path),
        cache_dir=tmp_path,
        now=NOW,
    )
    assert real is not None
    assert swapped is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_project_age_days_is_none_when_the_project_cannot_be_read(tmp_path: Path) -> None:
    project = _project(tmp_path, "app", age=100)
    assert project_age_days(project=project, now=NOW) == 100

    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("x")
    (project / "src").chmod(0o000)
    try:
        assert project_age_days(project=project, now=NOW) is None
    finally:
        (project / "src").chmod(0o700)
