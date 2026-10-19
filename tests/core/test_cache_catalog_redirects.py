from pathlib import Path

import pytest

from tests.core.cache_catalog_helpers import HOME, ROOTS, _resolved
from wimm.core.cache_catalog import (
    CacheAccess,
    CacheObservations,
    RejectReason,
    resolve_cache_paths,
    sentinel_candidates,
)
from wimm.model.disk import CacheKind


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


def _linked(*, link: Path, target: Path, kind: CacheKind) -> CacheObservations:
    sentinel = sentinel_candidates(kind=kind, path=target)[0]
    return CacheObservations(real={link: target}, sentinels=frozenset({sentinel}))


def test_a_redirect_through_a_link_is_measure_only_even_with_the_sentinel_on_its_target() -> None:
    link = Path("/home/u/shortcut")
    observed = _linked(link=link, target=Path("/home/u/gc"), kind=CacheKind.GO_BUILD)

    entry = _resolved(environ={"GOCACHE": str(link)}, observed=observed)["go_build"]

    assert entry.path == link
    assert entry.access is CacheAccess.MEASURE_ONLY


def test_a_desktop_xdg_cache_reached_through_a_link_is_measure_only() -> None:
    xdg = HOME / ".local" / "cache"
    link = xdg / "go-build"
    observed = CacheObservations(real={link: Path("/home/u/gc")})

    entry = _resolved(environ={"XDG_CACHE_HOME": str(xdg)}, observed=observed)["go_build"]

    assert entry.path == link
    assert entry.access is CacheAccess.MEASURE_ONLY


@pytest.mark.parametrize("target", [".cache", ".local", ".config", ".cache/uv"])
def test_a_harmless_looking_link_to_a_shared_or_other_cache_folder_is_refused(target: str) -> None:
    link = Path("/home/u/shortcut")
    observed = CacheObservations(real={link: HOME / target})

    result = resolve_cache_paths(
        environ={"GOCACHE": str(link)}, home=HOME, roots=ROOTS, observed=observed
    )

    assert "go_build" not in {entry.kind.value for entry in result.caches}
    assert result.rejected[0].reason is RejectReason.COVERS_OTHER_CACHES
