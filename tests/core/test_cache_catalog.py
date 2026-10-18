from pathlib import Path

import pytest

from wimm.core.cache_catalog import (
    CacheAccess,
    CacheObservations,
    RejectReason,
    ResolvedCache,
    resolve_cache_paths,
    sentinel_candidates,
)
from wimm.core.cache_specs import CACHE_COMMANDS, CACHE_SPECS, CacheBase, spec_for
from wimm.model.disk import CacheKind

NEW_KINDS = (
    "cargo_registry",
    "cargo_git",
    "gradle",
    "maven",
    "go_mod",
    "go_build",
    "yarn",
    "pnpm",
    "bun",
    "conda",
    "playwright",
    "jetbrains",
)


def test_cache_kind_has_the_twelve_new_types_beside_the_five_old_ones() -> None:
    values = {kind.value for kind in CacheKind}

    assert set(NEW_KINDS) <= values
    assert {"uv", "npm", "pip", "trash", "thumbnails"} <= values
    assert len(values) == 17


def test_every_cache_kind_has_exactly_one_spec() -> None:
    kinds = [spec.kind for spec in CACHE_SPECS]

    assert sorted(kind.value for kind in kinds) == sorted(kind.value for kind in CacheKind)


def test_the_five_original_caches_stay_where_they_always_were() -> None:
    home = Path("/home/u")

    found = {
        cache.kind.value: cache.path
        for cache in resolve_cache_paths(environ={}, home=home, roots=()).caches
    }

    assert found["uv"] == home / ".cache/uv"
    assert found["npm"] == home / ".npm/_cacache"
    assert found["pip"] == home / ".cache/pip"
    assert found["trash"] == home / ".local/share/Trash"
    assert found["thumbnails"] == home / ".cache/thumbnails"


def test_a_spec_names_the_variable_that_moves_the_tool_and_its_native_command() -> None:
    go_mod = spec_for(kind=CacheKind.GO_MOD)
    maven = spec_for(kind=CacheKind.MAVEN)

    assert go_mod.env_var == "GOMODCACHE"
    assert CACHE_COMMANDS[CacheKind.GO_MOD].env_var == "GOMODCACHE"
    assert spec_for(kind=CacheKind.CARGO_REGISTRY).env_var == "CARGO_HOME"
    assert CacheKind.CARGO_REGISTRY not in CACHE_COMMANDS
    assert maven.env_var is None
    assert maven.base is CacheBase.HOME
    assert maven.relative == ".m2/repository"


@pytest.mark.parametrize("kind", list(CacheKind))
def test_relative_paths_are_never_absolute_or_climbing(kind: CacheKind) -> None:
    relative = spec_for(kind=kind).relative

    assert relative and not relative.startswith("/")
    assert ".." not in relative.split("/")


# --- resolve_cache_paths (R12, S5) ---------------------------------------------------

HOME = Path("/home/u")
ROOT = Path("/home/u/projects")
ROOTS = (ROOT,)


def _paths(
    *, environ: dict[str, str], observed: CacheObservations | None = None
) -> dict[str, Path]:
    result = resolve_cache_paths(
        environ=environ, home=HOME, roots=ROOTS, observed=observed or CacheObservations()
    )
    return {entry.kind.value: entry.path for entry in result.caches}


def _resolved(
    *, environ: dict[str, str], observed: CacheObservations | None = None
) -> dict[str, ResolvedCache]:
    result = resolve_cache_paths(
        environ=environ, home=HOME, roots=ROOTS, observed=observed or CacheObservations()
    )
    return {entry.kind.value: entry for entry in result.caches}


def _sentinel(kind: CacheKind, path: Path) -> CacheObservations:
    sentinel = sentinel_candidates(kind=kind, path=path)[0]
    return CacheObservations(real={path: path}, sentinels=frozenset({sentinel}))


def test_resolve_cache_paths_without_variables_gives_the_default_folders() -> None:
    found = _paths(environ={})

    assert found["uv"] == Path("/home/u/.cache/uv")
    assert found["npm"] == Path("/home/u/.npm/_cacache")
    assert found["maven"] == Path("/home/u/.m2/repository")
    assert found["cargo_registry"] == Path("/home/u/.cargo/registry")
    assert found["go_build"] == Path("/home/u/.cache/go-build")
    assert found["playwright"] == Path("/home/u/.cache/ms-playwright")
    assert len(found) == 17


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
        environ={"HF_HOME": str(ROOT)}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert len(result.caches) == 17
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

    assert len(result.caches) == 17
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


def test_a_redirected_folder_without_a_sentinel_is_measure_only() -> None:
    entry = _resolved(environ={"GOCACHE": "/home/u/gocache"})["go_build"]

    assert entry.redirected is True
    assert entry.access is CacheAccess.MEASURE_ONLY


def test_a_redirected_folder_with_a_sentinel_is_cleanable() -> None:
    path = Path("/home/u/gocache")
    observed = _sentinel(CacheKind.GO_BUILD, path)

    entry = _resolved(environ={"GOCACHE": str(path)}, observed=observed)["go_build"]

    assert entry.redirected is True
    assert entry.access is CacheAccess.CLEANABLE


def test_a_sentinel_of_another_folder_does_not_unlock_the_redirected_one() -> None:
    gocache = Path("/home/u/gocache")
    other = _sentinel(CacheKind.GO_BUILD, Path("/home/u/elsewhere"))
    observed = CacheObservations(real={gocache: gocache}, sentinels=other.sentinels)

    entry = _resolved(environ={"GOCACHE": "/home/u/gocache"}, observed=observed)["go_build"]

    assert entry.access is CacheAccess.MEASURE_ONLY


def test_a_default_folder_is_cleanable_without_a_sentinel() -> None:
    entry = _resolved(environ={})["go_build"]

    assert entry.redirected is False
    assert entry.access is CacheAccess.CLEANABLE


def test_a_variable_equal_to_the_default_is_not_a_redirection() -> None:
    entry = _resolved(environ={"GOCACHE": "/home/u/.cache/go-build"})["go_build"]

    assert entry.redirected is False
    assert entry.access is CacheAccess.CLEANABLE


@pytest.mark.parametrize("kind", list(CacheKind))
def test_every_type_offers_the_generic_cachedir_tag_as_sentinel(kind: CacheKind) -> None:
    path = Path("/home/u/anywhere")

    assert Path("/home/u/anywhere/CACHEDIR.TAG") in sentinel_candidates(kind=kind, path=path)


def test_known_tool_subfolders_are_sentinels() -> None:
    go_mod = sentinel_candidates(kind=CacheKind.GO_MOD, path=Path("/home/u/gomod"))
    registry = sentinel_candidates(kind=CacheKind.CARGO_REGISTRY, path=Path("/home/u/c/registry"))

    assert Path("/home/u/gomod/cache/download") in go_mod
    assert Path("/home/u/c/registry/cache") in registry


# --- sentinels need more than a generic subfolder ------------------------------------

LAVORO = Path("/home/u/lavoro")


def _known(path: Path, *names: str, tag: bool = False) -> CacheObservations:
    found = {path / name for name in names} | ({path / "CACHEDIR.TAG"} if tag else set())
    return CacheObservations(real={path: path}, sentinels=frozenset(found))


def _pip_access(observed: CacheObservations) -> CacheAccess:
    environ = {"PIP_CACHE_DIR": str(LAVORO)}
    return _resolved(environ=environ, observed=observed)["pip"].access


def test_one_generic_subfolder_does_not_make_a_work_folder_cleanable() -> None:
    assert _pip_access(_known(LAVORO, "wheels")) is CacheAccess.MEASURE_ONLY


def test_two_known_entries_of_the_tool_make_it_cleanable() -> None:
    assert _pip_access(_known(LAVORO, "wheels", "http-v2")) is CacheAccess.CLEANABLE


def test_cachedir_tag_alone_makes_it_cleanable() -> None:
    assert _pip_access(_known(LAVORO, tag=True)) is CacheAccess.CLEANABLE


def test_a_tool_specific_file_alone_makes_it_cleanable() -> None:
    npm = Path("/home/u/npm-x/_cacache")
    conda = Path("/home/u/conda-x")
    environ = {"npm_config_cache": "/home/u/npm-x", "CONDA_PKGS_DIRS": str(conda)}
    observed = CacheObservations(
        real={npm: npm, conda: conda},
        sentinels=frozenset({npm / "index-v5", conda / "urls.txt"}),
    )

    found = _resolved(environ=environ, observed=observed)

    assert found["npm"].access is CacheAccess.CLEANABLE
    assert found["conda"].access is CacheAccess.CLEANABLE


def test_a_lone_generic_entry_of_another_tool_does_not_count() -> None:
    assert _pip_access(_known(LAVORO, "db", "checkouts")) is CacheAccess.MEASURE_ONLY


# --- fail closed: a path nobody resolved is not known to be real ---------------------


def test_a_redirected_folder_whose_real_path_was_not_supplied_is_measure_only() -> None:
    path = Path("/home/u/gocache")
    unresolved = CacheObservations(sentinels=_sentinel(CacheKind.GO_BUILD, path).sentinels)

    blind = _resolved(environ={"GOCACHE": str(path)}, observed=unresolved)["go_build"]
    sighted = _resolved(
        environ={"GOCACHE": str(path)}, observed=_sentinel(CacheKind.GO_BUILD, path)
    )

    assert blind.access is CacheAccess.MEASURE_ONLY
    assert sighted["go_build"].access is CacheAccess.CLEANABLE


def _default_uv(real: Path | None) -> tuple[list[ResolvedCache], list[RejectReason]]:
    default = Path("/home/u/.cache/uv")
    observed = CacheObservations(real={} if real is None else {default: real})
    result = resolve_cache_paths(environ={}, home=HOME, roots=ROOTS, observed=observed)
    caches = [c for c in result.caches if c.kind is CacheKind.UV]
    return caches, [r.reason for r in result.rejected if r.kind is CacheKind.UV]


def test_a_default_folder_that_resolves_into_a_root_is_refused() -> None:
    caches, reasons = _default_uv(real=Path("/home/u/projects/app/uvcache"))

    assert caches == []
    assert reasons == [RejectReason.ROOT_CONFLICT]


def test_a_default_folder_that_resolves_outside_the_home_is_refused() -> None:
    caches, reasons = _default_uv(real=Path("/mnt/disk/uv"))

    assert caches == []
    assert reasons == [RejectReason.OUTSIDE_HOME]


def test_a_default_folder_behind_a_link_inside_the_home_is_measure_only() -> None:
    caches, reasons = _default_uv(real=Path("/home/u/elsewhere/uv"))

    assert [c.access for c in caches] == [CacheAccess.MEASURE_ONLY]
    assert reasons == []
    assert _default_uv(real=None)[0][0].access is CacheAccess.CLEANABLE


# --- other spellings of the same variables -------------------------------------------


def test_npm_reads_the_uppercase_variable_too() -> None:
    upper = _paths(environ={"NPM_CONFIG_CACHE": "/home/u/npm-up"})["npm"]
    both = _paths(environ={"npm_config_cache": "/home/u/a", "NPM_CONFIG_CACHE": "/home/u/b"})["npm"]

    assert upper == Path("/home/u/npm-up/_cacache")
    assert both == Path("/home/u/a/_cacache")


def test_go_module_cache_follows_the_first_gopath_entry_when_gomodcache_is_unset() -> None:
    gopath = _paths(environ={"GOPATH": "/home/u/gp:/home/u/other"})["go_mod"]
    explicit = _paths(environ={"GOPATH": "/home/u/gp", "GOMODCACHE": "/home/u/mc"})["go_mod"]
    default = _paths(environ={"GOPATH": "/home/u/go"})["go_mod"]

    assert gopath == Path("/home/u/gp/pkg/mod")
    assert explicit == Path("/home/u/mc")
    assert default == Path("/home/u/go/pkg/mod")


def test_a_gopath_on_a_root_is_refused_like_any_other_redirection() -> None:
    result = resolve_cache_paths(
        environ={"GOPATH": str(ROOT)}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    assert "go_mod" not in {c.kind.value for c in result.caches}
    assert [r.reason for r in result.rejected] == [RejectReason.ROOT_CONFLICT]


def test_xdg_cache_home_is_a_desktop_standard_and_needs_no_sentinel() -> None:
    xdg = HOME / ".local" / "cache"

    result = resolve_cache_paths(
        environ={"XDG_CACHE_HOME": str(xdg)}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    by_kind = {entry.kind.value: entry for entry in result.caches}
    for kind, name in (("uv", "uv"), ("thumbnails", "thumbnails"), ("go_build", "go-build")):
        assert by_kind[kind].path == xdg / name
        assert by_kind[kind].access is CacheAccess.CLEANABLE
    assert by_kind["jetbrains"].access is CacheAccess.CLEANABLE


def test_a_tool_variable_without_a_sentinel_stays_measure_only() -> None:
    redirected = HOME / "elsewhere" / "uv"

    result = resolve_cache_paths(
        environ={"UV_CACHE_DIR": str(redirected)},
        home=HOME,
        roots=ROOTS,
        observed=CacheObservations(real={redirected: redirected}),
    )

    uv = next(entry for entry in result.caches if entry.kind.value == "uv")
    assert uv.access is CacheAccess.MEASURE_ONLY


def test_a_default_cache_resolved_elsewhere_inside_the_home_is_not_cleanable() -> None:
    default = HOME / ".cache" / "thumbnails"
    docs = HOME / "Documents"

    result = resolve_cache_paths(
        environ={}, home=HOME, roots=ROOTS, observed=CacheObservations(real={default: docs})
    )

    thumbs = next(entry for entry in result.caches if entry.kind.value == "thumbnails")
    assert thumbs.path == default and thumbs.access is CacheAccess.MEASURE_ONLY


def test_xdg_cache_home_without_cache_in_its_name_keeps_the_sentinel_rule() -> None:
    result = resolve_cache_paths(
        environ={"XDG_CACHE_HOME": str(HOME / "Documents")},
        home=HOME,
        roots=ROOTS,
        observed=CacheObservations(),
    )

    thumbs = next(entry for entry in result.caches if entry.kind.value == "thumbnails")
    assert thumbs.access is CacheAccess.MEASURE_ONLY


def _bun_at(*, folder: Path, tagged: bool) -> tuple[list[str], str | None]:
    """Resolve BUN_INSTALL_CACHE_DIR=folder, with a CACHEDIR.TAG in it when ``tagged``."""
    observed = CacheObservations(
        real={folder: folder},
        sentinels=frozenset({folder / "CACHEDIR.TAG"}) if tagged else frozenset(),
    )
    result = resolve_cache_paths(
        environ={"BUN_INSTALL_CACHE_DIR": str(folder)}, home=HOME, roots=ROOTS, observed=observed
    )
    bun = next((c for c in result.caches if c.kind is CacheKind.BUN), None)
    return [r.reason for r in result.rejected], None if bun is None else bun.access


def test_a_redirect_onto_the_cache_folder_of_the_home_is_refused_even_with_a_cache_tag() -> None:
    reasons, access = _bun_at(folder=HOME / ".cache", tagged=True)

    assert reasons == [RejectReason.COVERS_OTHER_CACHES]
    assert access is None


@pytest.mark.parametrize(
    "folder",
    [
        HOME / ".local",
        HOME / ".local" / "share",
        HOME / ".config",
        HOME / ".cargo",
        HOME / ".cache" / "uv",
    ],
)
def test_a_redirect_onto_a_shared_folder_or_another_cache_is_refused(folder: Path) -> None:
    reasons, access = _bun_at(folder=folder, tagged=True)

    assert reasons == [RejectReason.COVERS_OTHER_CACHES]
    assert access is None


def test_a_redirect_to_a_folder_of_its_own_with_a_cache_tag_is_cleanable() -> None:
    reasons, access = _bun_at(folder=HOME / "bun-cache", tagged=True)

    assert reasons == []
    assert access is CacheAccess.CLEANABLE


def test_xdg_cache_home_named_exactly_cache_needs_no_sentinel_in_any_case() -> None:
    for name in ("cache", "Cache"):
        xdg = HOME / ".local" / name
        result = resolve_cache_paths(
            environ={"XDG_CACHE_HOME": str(xdg)},
            home=HOME,
            roots=ROOTS,
            observed=CacheObservations(),
        )

        uv = next(entry for entry in result.caches if entry.kind is CacheKind.UV)
        assert uv.path == xdg / "uv" and uv.access is CacheAccess.CLEANABLE


def test_xdg_cache_home_that_only_contains_cache_in_its_name_is_not_trusted() -> None:
    xdg = HOME / "Documents" / "cachet-notes"

    result = resolve_cache_paths(
        environ={"XDG_CACHE_HOME": str(xdg)}, home=HOME, roots=ROOTS, observed=CacheObservations()
    )

    uv = next(entry for entry in result.caches if entry.kind is CacheKind.UV)
    assert uv.access is CacheAccess.MEASURE_ONLY
