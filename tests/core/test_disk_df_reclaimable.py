from typing import Any

from wimm.core.disk_rules import parse_docker_df, unavailable_docker

from .disk_helpers import MB, load_df, sha


def _df(
    *, images: list[dict[str, Any]] | None = None, cache: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"Images": images, "BuildCache": cache, "Containers": [], "Volumes": []}


def _raw_image(*, char: str, size: int, **extra: Any) -> dict[str, Any]:
    return {
        "Id": sha(char),
        "RepoTags": ["app:1"],
        "RepoDigests": ["app@sha256:" + char * 64],
        "Containers": 0,
        "Size": size,
        **extra,
    }


def _record(*, size: int, in_use: bool = False, shared: bool = False) -> dict[str, Any]:
    return {"ID": "x", "InUse": in_use, "Shared": shared, "Size": size}


def test_unique_size_is_size_minus_shared_size_while_size_stays_whole() -> None:
    df = _df(images=[_raw_image(char="a", size=100 * MB, SharedSize=40 * MB)])

    (parsed,) = parse_docker_df(df=df).images

    assert parsed.size == 100 * MB
    assert parsed.unique_size == 60 * MB


def test_unique_size_falls_back_to_size_when_shared_size_is_missing() -> None:
    (parsed,) = parse_docker_df(df=_df(images=[_raw_image(char="a", size=100 * MB)])).images

    assert parsed.unique_size == 100 * MB


def test_unique_size_falls_back_to_size_when_shared_size_not_computed() -> None:
    df = _df(images=[_raw_image(char="a", size=100 * MB, SharedSize=-1)])

    (parsed,) = parse_docker_df(df=df).images

    assert parsed.unique_size == 100 * MB


def test_unique_size_is_clamped_to_zero_when_shared_size_exceeds_size() -> None:
    df = _df(images=[_raw_image(char="a", size=100 * MB, SharedSize=150 * MB)])

    (parsed,) = parse_docker_df(df=df).images

    assert parsed.unique_size == 0


def test_unique_size_equals_size_when_nothing_is_shared() -> None:
    df = _df(images=[_raw_image(char="a", size=100 * MB, SharedSize=0)])

    (parsed,) = parse_docker_df(df=df).images

    assert parsed.unique_size == 100 * MB


def test_build_cache_reclaimable_counts_only_records_neither_in_use_nor_shared() -> None:
    cache = [
        _record(size=50 * MB),
        _record(size=30 * MB, in_use=True),
        _record(size=20 * MB, shared=True),
        _record(size=10 * MB, in_use=True, shared=True),
        _record(size=7 * MB),
    ]

    docker = parse_docker_df(df=_df(cache=cache))

    assert docker.build_cache_size == 117 * MB
    assert docker.build_cache_reclaimable == 57 * MB


def test_build_cache_reclaimable_on_the_fixture_skips_the_in_use_record() -> None:
    docker = parse_docker_df(df=load_df())

    assert docker.build_cache_size == 100 * MB
    assert docker.build_cache_reclaimable == 70 * MB


def test_build_cache_reclaimable_is_zero_for_an_empty_cache() -> None:
    assert parse_docker_df(df=_df(cache=None)).build_cache_reclaimable == 0
    assert unavailable_docker(error="down").build_cache_reclaimable == 0
