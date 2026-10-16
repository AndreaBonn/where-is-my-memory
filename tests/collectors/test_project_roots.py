from pathlib import Path

from wimm.collectors.project_roots import ProjectRootResolver


def resolver(home: Path) -> ProjectRootResolver:
    # Markers outside the test tree (e.g. in /tmp) must not leak into the walk.
    sandbox = home.parent
    return ProjectRootResolver(
        is_marker=lambda path: path.is_relative_to(sandbox) and path.exists(), home=home
    )


def test_nested_project_uses_nearest_marker(tmp_path: Path) -> None:
    project = tmp_path / "project"
    cwd = project / "src" / "nested"
    cwd.mkdir(parents=True)
    (project / "pyproject.toml").touch()
    assert resolver(home=tmp_path / "home").resolve(cwd=cwd) == project
    (cwd.parent / "package.json").touch()
    assert resolver(home=tmp_path / "home").resolve(cwd=cwd) == project / "src"


def test_marker_created_later_is_seen_by_next_resolver(tmp_path: Path) -> None:
    cwd = tmp_path / "project" / "src"
    cwd.mkdir(parents=True)
    first = resolver(home=tmp_path / "home")
    assert first.resolve(cwd=cwd) == cwd
    (tmp_path / "project" / ".git").mkdir()
    assert first.resolve(cwd=cwd) == cwd
    assert resolver(home=tmp_path / "home").resolve(cwd=cwd) == tmp_path / "project"


def test_no_marker_returns_original_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "empty"
    cwd.mkdir()
    assert ProjectRootResolver(is_marker=lambda path: False).resolve(cwd=cwd) == cwd


def test_home_is_not_a_candidate_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = home / "a" / "b"
    cwd.mkdir(parents=True)
    (home / ".git").mkdir()
    assert resolver(home=home).resolve(cwd=cwd) == cwd
    assert resolver(home=home).resolve(cwd=home) == home
    (home / "a" / ".git").mkdir()
    assert resolver(home=home).resolve(cwd=cwd) == home / "a"


def test_marker_above_home_is_not_reached(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = home / "nested"
    cwd.mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    assert resolver(home=home).resolve(cwd=cwd) == cwd


def test_outside_home_reaches_filesystem_root(tmp_path: Path) -> None:
    result = ProjectRootResolver(
        is_marker=lambda path: path == Path("/.git"), home=tmp_path / "home"
    ).resolve(cwd=tmp_path)
    assert result == Path("/")
