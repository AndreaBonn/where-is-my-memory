from pathlib import Path

import pytest

from tests.core.cache_catalog_helpers import HOME, ROOT, ROOTS, _paths
from wimm.core.cache_catalog import (
    CacheAccess,
    CacheObservations,
    RejectReason,
    resolve_cache_paths,
)


def test_resolve_cache_paths_without_variables_gives_the_default_folders() -> None:
    found = _paths(environ={})

    assert found["uv"] == Path("/home/u/.cache/uv")
    assert found["npm"] == Path("/home/u/.npm/_cacache")
    assert found["maven"] == Path("/home/u/.m2/repository")
    assert found["cargo_registry"] == Path("/home/u/.cargo/registry")
    assert found["go_build"] == Path("/home/u/.cache/go-build")
    assert found["playwright"] == Path("/home/u/.cache/ms-playwright")
    assert len(found) == 21


def test_resolve_cache_paths_honours_xdg_and_tool_variables() -> None:
    environ = {
        "XDG_CACHE_HOME": "/home/u/xdg",
        "CARGO_HOME": "/home/u/cargo-x",
        "GOMODCACHE": "/home/u/gomod",
        "GOCACHE": "/home/u/gobuild",
        "GRADLE_USER_HOME": "/home/u/gradle-x",
        "YARN_CACHE_FOLDER": "/home/u/yarn-x",
        "BUN_INSTALL_CACHE_DIR": "/home/u/bun-x",
        "CONDA_PKGS_DIRS": "/home/u/conda-a,/home/u/conda-b",
        "PLAYWRIGHT_BROWSERS_PATH": "/home/u/browsers",
        "UV_CACHE_DIR": "/home/u/uv-x",
        "PIP_CACHE_DIR": "/home/u/pip-x",
        "npm_config_cache": "/home/u/npm-x",
    }

    found = _paths(environ=environ)

    assert found == {
        "uv": Path("/home/u/uv-x"),
        "npm": Path("/home/u/npm-x/_cacache"),
        "pip": Path("/home/u/pip-x"),
        "trash": Path("/home/u/.local/share/Trash"),
        "thumbnails": Path("/home/u/xdg/thumbnails"),
        "cargo_registry": Path("/home/u/cargo-x/registry"),
        "cargo_git": Path("/home/u/cargo-x/git"),
        "gradle": Path("/home/u/gradle-x/caches"),
        "maven": Path("/home/u/.m2/repository"),
        "go_mod": Path("/home/u/gomod"),
        "go_build": Path("/home/u/gobuild"),
        "yarn": Path("/home/u/yarn-x"),
        "pnpm": Path("/home/u/.local/share/pnpm/store"),
        "bun": Path("/home/u/bun-x"),
        "conda": Path("/home/u/conda-a"),
        "playwright": Path("/home/u/browsers"),
        "jetbrains": Path("/home/u/xdg/JetBrains"),
        "huggingface": Path("/home/u/xdg/huggingface/hub"),
        "ollama": Path("/home/u/.ollama/models"),
        "android_avd": Path("/home/u/.android/avd"),
        "android_sdk": Path("/home/u/Android/Sdk"),
    }


def test_an_empty_variable_counts_as_unset() -> None:
    assert _paths(environ={"GOCACHE": ""})["go_build"] == Path("/home/u/.cache/go-build")


@pytest.mark.parametrize(
    "variable,kind",
    [("GOCACHE", "go_build"), ("GOMODCACHE", "go_mod"), ("PIP_CACHE_DIR", "pip")],
)
def test_a_variable_pointing_at_the_home_is_refused(variable: str, kind: str) -> None:
    result = resolve_cache_paths(
        environ={variable: str(HOME)}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert kind not in {entry.kind.value for entry in result.caches}
    assert [(r.kind.value, r.reason) for r in result.rejected] == [kind_reason(kind)]


def kind_reason(kind: str) -> tuple[str, RejectReason]:
    return kind, RejectReason.OUTSIDE_HOME


def test_a_variable_pointing_above_the_home_is_refused() -> None:
    result = resolve_cache_paths(
        environ={"GOMODCACHE": "/home"}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert "go_mod" not in {entry.kind.value for entry in result.caches}
    assert result.rejected[0].reason is RejectReason.OUTSIDE_HOME


def test_a_variable_that_climbs_out_of_the_home_is_refused() -> None:
    environ = {"GOCACHE": "/home/u/.cache/../../etc"}

    assert "go_build" not in _paths(environ=environ)
    assert "go_build" in _paths(environ={"GOCACHE": "/home/u/.cache/../gocache"})


@pytest.mark.parametrize(
    "value",
    [str(ROOT), "/home/u/projects/app/.gocache", "/home/u/projects/a/../b"],
)
def test_a_variable_equal_to_or_inside_a_root_is_refused(value: str) -> None:
    result = resolve_cache_paths(
        environ={"GOCACHE": value}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert "go_build" not in {entry.kind.value for entry in result.caches}
    assert result.rejected[0].reason is RejectReason.ROOT_CONFLICT


def test_a_variable_above_a_root_is_refused_beside_its_accepted_twin() -> None:
    root = Path("/home/u/work/projects")
    refused = resolve_cache_paths(
        environ={"GOCACHE": "/home/u/work"}, home=HOME, roots=(root,), observed=CacheObservations()
    )
    accepted = resolve_cache_paths(
        environ={"GOCACHE": "/home/u/other"}, home=HOME, roots=(root,), observed=CacheObservations()
    )

    assert "go_build" not in {entry.kind.value for entry in refused.caches}
    assert refused.rejected[0].reason is RejectReason.ROOT_CONFLICT
    assert "go_build" in {entry.kind.value for entry in accepted.caches}


def test_an_unrelated_variable_pointing_at_a_root_is_not_a_cache() -> None:
    result = resolve_cache_paths(
        environ={"UNRELATED_HOME": str(ROOT)}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert len(result.caches) == 21
    assert result.rejected == ()


def test_xdg_cache_home_on_a_root_refuses_what_hangs_from_it_and_keeps_the_rest() -> None:
    result = resolve_cache_paths(
        environ={"XDG_CACHE_HOME": str(ROOT)},
        home=HOME,
        roots=ROOTS,
        observed=CacheObservations(),
    )

    kept = {entry.kind.value for entry in result.caches}
    assert "uv" not in kept and "jetbrains" not in kept
    assert {"maven", "cargo_registry"} <= kept
    assert {r.kind.value for r in result.rejected} >= {"uv", "pip", "go_build", "jetbrains"}


def test_a_root_equal_to_the_home_does_not_refuse_the_default_folders() -> None:
    result = resolve_cache_paths(environ={}, home=HOME, roots=(HOME,), observed=CacheObservations())

    assert len(result.caches) == 21
    assert all(entry.access is CacheAccess.CLEANABLE for entry in result.caches)


def test_a_variable_outside_the_home_is_refused_and_one_inside_is_kept() -> None:
    outside = resolve_cache_paths(
        environ={"GOCACHE": "/mnt/disk/gocache"},
        home=HOME,
        roots=ROOTS,
        observed=CacheObservations(),
    )

    assert "go_build" not in {entry.kind.value for entry in outside.caches}
    assert outside.rejected[0].reason is RejectReason.OUTSIDE_HOME
    assert "go_build" in _paths(environ={"GOCACHE": "/home/u/gocache"})


@pytest.mark.parametrize("value", ["relative/dir", "~/gocache", "0"])
def test_a_variable_that_is_not_an_absolute_path_is_refused(value: str) -> None:
    result = resolve_cache_paths(
        environ={"GOCACHE": value}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert "go_build" not in {entry.kind.value for entry in result.caches}
    assert result.rejected[0].reason is RejectReason.NOT_ABSOLUTE


def test_a_redirected_folder_that_is_really_the_home_is_refused() -> None:
    link = Path("/home/u/shortcut")
    observed = CacheObservations(real={link: HOME})

    refused = _paths(environ={"GOCACHE": str(link)}, observed=observed)
    kept = _paths(
        environ={"GOCACHE": str(link)}, observed=CacheObservations(real={link: Path("/home/u/gc")})
    )

    assert "go_build" not in refused
    # Behind a link: kept for measuring at its own path, never cleaned.
    assert kept["go_build"] == link
