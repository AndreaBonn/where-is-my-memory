from pathlib import Path

import pytest

from wimm.core.cache_catalog import (
    resolve_cache_paths,
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


def test_cache_kind_has_the_twelve_new_types_beside_the_five_old_ones_and_the_model_four() -> None:
    values = {kind.value for kind in CacheKind}

    assert set(NEW_KINDS) <= values
    assert {"uv", "npm", "pip", "trash", "thumbnails"} <= values
    assert len(values) == 21


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
