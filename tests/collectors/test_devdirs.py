import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from wimm.collectors.devdir_context import GITIGNORE_MAX_BYTES
from wimm.collectors.devdirs import DevDirScan, DevDirSettings, project_age_days, scan_devdirs
from wimm.core.constants import DIRSIZE_YIELD_EVERY
from wimm.core.devdir_rules import CACHEDIR_TAG, VENV_MARKER

NOW = 1_800_000_000.0
DAY = 86400


def _age(path: Path, days: float) -> None:
    stamp = NOW - days * DAY
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _scan(
    root: Path,
    tmp_path: Path,
    *,
    max_depth: int = 6,
    sleeps: list[float] | None = None,
    home: Path | None = None,
) -> DevDirScan:
    record = sleeps if sleeps is not None else []
    settings = DevDirSettings(
        roots=(root,), home=home if home is not None else tmp_path, max_depth=max_depth
    )
    return scan_devdirs(
        settings=settings, cache_dir=tmp_path / "sizes", now=NOW, sleep=record.append
    )


def _paths(result: DevDirScan) -> set[str]:
    return {item.path for item in result.devdirs}


def _project(root: Path, name: str, *, age: float = 100) -> Path:
    project = root / name
    project.mkdir(parents=True)
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.js").write_bytes(b"x" * 5000)
    (project / "setup.py").write_text("x")
    _age(project / "setup.py", age)
    return project


def _venv(path: Path) -> Path:
    """A virtual environment as the scan recognises it: the folder holds ``pyvenv.cfg``."""
    (path / "lib").mkdir(parents=True)
    (path / VENV_MARKER).write_text("home = /usr/bin\n")
    return path


def _build(project: Path, *, marker: str, folder: str, signal: str | None = None) -> Path:
    """A project with a ``marker`` file, a ``folder`` of output and the second ``signal``."""
    project.mkdir(parents=True, exist_ok=True)
    (project / marker).write_text("x")
    output = project / folder
    (output / "debug").mkdir(parents=True)
    (output / "debug" / "artifact.bin").write_bytes(b"x" * 100)
    if signal == CACHEDIR_TAG:
        (output / CACHEDIR_TAG).write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    elif signal == "gitignore":
        (project / ".gitignore").write_text(f"*.log\n/{folder}/\n")
    _age(project / marker, 100)
    return output


def test_scan_finds_node_modules_and_venv_with_sizes_and_fingerprint(tmp_path: Path) -> None:
    root = tmp_path / "work"
    web = _project(root, "web")
    py = root / "py"
    _venv(py / ".venv")
    (py / ".venv" / "lib.py").write_bytes(b"y" * 9000)
    result = _scan(root, tmp_path)
    assert _paths(result) == {str(web / "node_modules"), str(py / ".venv")}
    by_path = {item.path: item for item in result.devdirs}
    node = by_path[str(web / "node_modules")]
    blocks = (
        os.lstat(web / "node_modules").st_blocks
        + os.lstat(web / "node_modules" / "dep.js").st_blocks
    )
    assert node.size == blocks * 512
    info = os.lstat(web / "node_modules")
    assert (node.st_ino, node.st_dev) == (info.st_ino, info.st_dev)
    assert result.error_count == 0


def test_scan_symlinked_node_modules_not_reported(tmp_path: Path) -> None:
    root = tmp_path / "work"
    real = _project(root, "real")
    outside = tmp_path / "outside" / "node_modules"
    outside.mkdir(parents=True)
    linked = root / "linked"
    linked.mkdir()
    (linked / "node_modules").symlink_to(outside, target_is_directory=True)
    assert _paths(_scan(root, tmp_path)) == {str(real / "node_modules")}


def test_scan_symlinked_directory_is_not_descended(tmp_path: Path) -> None:
    root = tmp_path / "work"
    outside = tmp_path / "outside"
    _project(outside, "hidden-project")
    root.mkdir()
    (root / "portal").symlink_to(outside, target_is_directory=True)
    visible = _project(root, "visible")
    assert _paths(_scan(root, tmp_path)) == {str(visible / "node_modules")}


def test_scan_nested_node_modules_inside_node_modules_not_reported(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = _project(root, "app")
    nested = project / "node_modules" / "pkg" / "node_modules"
    nested.mkdir(parents=True)
    _venv(project / ".venv")
    (project / ".venv" / "lib" / "node_modules").mkdir(parents=True)
    result = _scan(root, tmp_path)
    assert _paths(result) == {str(project / "node_modules"), str(project / ".venv")}


def test_scan_hidden_directory_skipped_but_venv_found(tmp_path: Path) -> None:
    root = tmp_path / "work"
    _project(root / ".hidden", "buried")
    _project(root / "visible", "inner")
    (root / ".cache" / "node_modules").mkdir(parents=True)
    _venv(root / "proj" / ".venv")
    result = _scan(root, tmp_path)
    assert _paths(result) == {
        str(root / "visible" / "inner" / "node_modules"),
        str(root / "proj" / ".venv"),
    }


def test_scan_depth_boundary_max_found_max_plus_one_not(tmp_path: Path) -> None:
    root = tmp_path / "work"
    at_max = root / "a" / "b" / "node_modules"
    beyond = root / "a" / "b" / "c" / "node_modules"
    at_max.mkdir(parents=True)
    beyond.mkdir(parents=True)
    result = _scan(root, tmp_path, max_depth=3)
    assert _paths(result) == {str(at_max)}


def test_scan_depth_one_finds_only_direct_children(tmp_path: Path) -> None:
    root = tmp_path / "work"
    (root / "node_modules").mkdir(parents=True)
    (root / "sub" / "node_modules").mkdir(parents=True)
    assert _paths(_scan(root, tmp_path, max_depth=1)) == {str(root / "node_modules")}


def test_scan_age_from_first_level_files_in_whole_days(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = _project(root, "app", age=100)
    (project / "README.md").write_text("x")
    _age(project / "README.md", 40.6)
    item = _scan(root, tmp_path).devdirs[0]
    assert item.age_days == 40


def test_scan_age_uses_src_first_level_and_ignores_deeper_files(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = _project(root, "app", age=100)
    deep = project / "src" / "pkg"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x")
    (project / "src" / "main.py").write_text("x")
    (project / "docs").mkdir()
    (project / "docs" / "new.md").write_text("x")
    _age(project / "src" / "main.py", 10)
    _age(deep, 90)
    _age(project / "src", 90)
    _age(project / "docs", 80)
    _age(deep / "deep.py", 0)
    _age(project / "docs" / "new.md", 0)
    assert _scan(root, tmp_path).devdirs[0].age_days == 10


def test_scan_age_excludes_the_devdir_itself(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = _project(root, "app", age=55)
    _age(project / "node_modules", 0)
    assert _scan(root, tmp_path).devdirs[0].age_days == 55


def test_scan_age_of_project_without_other_entries_uses_project_mtime(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = root / "bare"
    (project / "node_modules").mkdir(parents=True)
    _age(project, 33)
    assert _scan(root, tmp_path).devdirs[0].age_days == 33


def test_scan_age_never_negative_for_future_mtime(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = _project(root, "app")
    _age(project / "setup.py", -5)
    assert _scan(root, tmp_path).devdirs[0].age_days == 0


def test_scan_hard_links_counted_once(tmp_path: Path) -> None:
    root = tmp_path / "work"
    project = _project(root, "app")
    os.link(src=project / "node_modules" / "dep.js", dst=project / "node_modules" / "alias.js")
    item = _scan(root, tmp_path).devdirs[0]
    blocks = (
        os.lstat(project / "node_modules").st_blocks
        + os.lstat(project / "node_modules" / "dep.js").st_blocks
    )
    assert item.size == blocks * 512


def test_scan_missing_root_and_root_outside_home_are_skipped(tmp_path: Path) -> None:
    home = tmp_path / "home2"
    inside = home / "work"
    outside = tmp_path / "elsewhere"
    kept = _project(inside, "app")
    _project(outside, "foreign")
    settings = DevDirSettings(roots=(home / "missing", outside, inside), home=home, max_depth=6)
    result = scan_devdirs(
        settings=settings, cache_dir=tmp_path / "sizes", now=NOW, sleep=lambda _s: None
    )
    assert _paths(result) == {str(kept / "node_modules")}


def test_scan_symlinked_root_is_skipped(tmp_path: Path) -> None:
    home = tmp_path / "home2"
    real = home / "real"
    _project(real, "app")
    link = home / "link"
    link.symlink_to(real, target_is_directory=True)
    assert _scan(link, tmp_path, home=home).devdirs == ()
    assert len(_scan(real, tmp_path, home=home).devdirs) == 1


@pytest.fixture
def locked_dir(tmp_path: Path) -> Iterator[Path]:
    locked = tmp_path / "work" / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0)
    try:
        yield locked
    finally:
        locked.chmod(stat.S_IRWXU)


def test_scan_unreadable_directory_counted_not_raised(tmp_path: Path, locked_dir: Path) -> None:
    root = tmp_path / "work"
    ok = _project(root, "ok")
    result = _scan(root, tmp_path)
    assert result.error_count >= 1
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
    assert 0 in sleeps


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


def test_age_ignores_build_output_folders(tmp_path: Path) -> None:
    rust = tmp_path / "work" / "rust"
    target = _build(rust, marker="Cargo.toml", folder="target", signal=CACHEDIR_TAG)
    _age(rust / "Cargo.toml", 200)
    (rust / "build").mkdir()
    (rust / "vendor").mkdir()
    for fresh in (target, rust / "build", rust / "vendor"):
        _age(fresh, 0)
    result = _scan(tmp_path / "work", tmp_path)
    assert _paths(result) == {str(target)}
    assert [item.age_days for item in result.devdirs] == [200]
    assert project_age_days(project=rust, now=NOW) == 200


def test_age_still_counts_a_recently_edited_source_file(tmp_path: Path) -> None:
    rust = tmp_path / "work" / "rust"
    _build(rust, marker="Cargo.toml", folder="target", signal=CACHEDIR_TAG)
    (rust / "main.rs").write_text("fn main() {}")
    _age(rust / "main.rs", 3)
    assert project_age_days(project=rust, now=NOW) == 3


@pytest.mark.parametrize(
    ("marker", "folder", "signal"),
    [
        ("Cargo.toml", "target", CACHEDIR_TAG),
        ("pom.xml", "target", "gitignore"),
        ("build.gradle", "build", "gitignore"),
        ("settings.gradle.kts", ".gradle", "gitignore"),
        ("package.json", ".next", "gitignore"),
        ("package.json", ".nuxt", CACHEDIR_TAG),
        ("composer.json", "vendor", "gitignore"),
        ("tox.ini", ".tox", None),
        ("pyproject.toml", ".tox", None),
    ],
)
def test_scan_finds_each_ecosystem_output_folder(
    tmp_path: Path, marker: str, folder: str, signal: str | None
) -> None:
    output = _build(tmp_path / "work" / "p", marker=marker, folder=folder, signal=signal)
    assert _paths(_scan(tmp_path / "work", tmp_path)) == {str(output)}


@pytest.mark.parametrize(
    ("marker", "folder", "signal"),
    [
        ("Cargo.toml", "target", None),
        ("pom.xml", "target", None),
        ("build.gradle", "build", None),
        ("package.json", ".next", None),
        ("composer.json", "vendor", None),
        ("go.mod", "vendor", "gitignore"),
        ("README.md", "target", CACHEDIR_TAG),
        ("README.md", "build", "gitignore"),
        ("README.md", ".tox", None),
        ("package.json", "dist", "gitignore"),
        ("package.json", ".gradle", "gitignore"),
    ],
)
def test_scan_refuses_a_folder_without_its_marker_or_second_signal(
    tmp_path: Path, marker: str, folder: str, signal: str | None
) -> None:
    _build(tmp_path / "work" / "p", marker=marker, folder=folder, signal=signal)
    assert _paths(_scan(tmp_path / "work", tmp_path)) == set()


def test_scan_refuses_a_venv_folder_without_pyvenv_cfg(tmp_path: Path) -> None:
    (tmp_path / "work" / "p" / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / "work" / "q" / "venv").mkdir(parents=True)
    _venv(tmp_path / "work" / "r" / "venv")
    assert _paths(_scan(tmp_path / "work", tmp_path)) == {str(tmp_path / "work" / "r" / "venv")}


def test_scan_refuses_a_project_directly_in_the_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _build(home, marker="settings.gradle", folder=".gradle", signal=CACHEDIR_TAG)
    (home / "node_modules").mkdir()
    deeper = _build(home / "work" / "app", marker="Cargo.toml", folder="target", signal="gitignore")
    assert _paths(_scan(home, tmp_path, home=home)) == {str(deeper)}


def test_scan_ignores_a_gitignore_that_is_too_large_or_a_symlink(tmp_path: Path) -> None:
    big = _build(tmp_path / "work" / "big", marker="Cargo.toml", folder="target")
    padding = "#" * GITIGNORE_MAX_BYTES
    (big.parent / ".gitignore").write_text(f"{padding}\ntarget\n")
    linked = _build(tmp_path / "work" / "linked", marker="Cargo.toml", folder="target")
    real = tmp_path / "elsewhere"
    real.write_text("target\n")
    (linked.parent / ".gitignore").symlink_to(real)
    ok = _build(tmp_path / "work" / "ok", marker="Cargo.toml", folder="target", signal="gitignore")
    assert _paths(_scan(tmp_path / "work", tmp_path)) == {str(ok)}


def test_scan_gitignore_negation_withdraws_the_signal(tmp_path: Path) -> None:
    output = _build(tmp_path / "work" / "p", marker="Cargo.toml", folder="target")
    (output.parent / ".gitignore").write_text("target/\n!target/\n")
    assert _paths(_scan(tmp_path / "work", tmp_path)) == set()


def test_scan_hidden_table_names_are_found_but_other_hidden_folders_are_not(
    tmp_path: Path,
) -> None:
    found = _build(
        tmp_path / "work" / "a", marker="package.json", folder=".next", signal="gitignore"
    )
    _build(
        tmp_path / "work" / ".hidden" / "b",
        marker="Cargo.toml",
        folder="target",
        signal=CACHEDIR_TAG,
    )
    _build(tmp_path / "work" / "c", marker="package.json", folder=".cache", signal="gitignore")
    assert _paths(_scan(tmp_path / "work", tmp_path)) == {str(found)}


def test_scan_does_not_descend_into_a_folder_it_found(tmp_path: Path) -> None:
    output = _build(
        tmp_path / "work" / "p", marker="Cargo.toml", folder="target", signal=CACHEDIR_TAG
    )
    inner = _build(output / "inner", marker="Cargo.toml", folder="target", signal=CACHEDIR_TAG)
    assert inner.exists()
    assert _paths(_scan(tmp_path / "work", tmp_path)) == {str(output)}


def test_scan_descends_into_a_table_name_that_was_refused(tmp_path: Path) -> None:
    refused = tmp_path / "work" / "target"
    refused.mkdir(parents=True)
    nested = _build(refused / "app", marker="Cargo.toml", folder="target", signal=CACHEDIR_TAG)
    assert _paths(_scan(tmp_path / "work", tmp_path)) == {str(nested)}


def test_scan_records_the_marker_that_names_the_rebuild_command(tmp_path: Path) -> None:
    root = tmp_path / "work"
    _build(root / "crate", marker="Cargo.toml", folder="target", signal=CACHEDIR_TAG)
    _build(root / "app", marker="pom.xml", folder="target", signal="gitignore")
    (root / "web" / "node_modules").mkdir(parents=True)
    markers = {Path(item.path).parent.name: item.marker for item in _scan(root, tmp_path).devdirs}
    assert markers == {"crate": "Cargo.toml", "app": "pom.xml", "web": ""}
