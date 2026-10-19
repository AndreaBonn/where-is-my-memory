from pathlib import Path

import pytest

from tests.core.cache_catalog_helpers import _resolved, _sentinel
from wimm.core.cache_catalog import (
    CacheAccess,
    CacheObservations,
    sentinel_candidates,
)
from wimm.model.disk import CacheKind


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
