from pathlib import Path

import pytest

from tests.collectors.devdirs_helpers import NOW, _age, _build, _paths, _scan, _venv
from wimm.collectors.devdir_context import GITIGNORE_MAX_BYTES
from wimm.collectors.devdirs import project_age_days
from wimm.core.devdir_rules import CACHEDIR_TAG


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
