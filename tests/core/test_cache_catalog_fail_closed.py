from pathlib import Path

from tests.core.cache_catalog_helpers import HOME, ROOT, ROOTS, _paths, _resolved, _sentinel
from wimm.core.cache_catalog import (
    CacheAccess,
    CacheObservations,
    RejectReason,
    ResolvedCache,
    resolve_cache_paths,
)
from wimm.model.disk import CacheKind

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
