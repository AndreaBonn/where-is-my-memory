from wimm.core.disk_rules import safe_reclaimable_bytes, unavailable_docker
from wimm.model.disk import CacheKind

from .disk_helpers import MB, cache, devdir, docker_disk, image, report, stopped, volume


def test_safe_reclaimable_bytes_without_a_report_is_zero() -> None:
    assert safe_reclaimable_bytes(report=None) == 0


def test_safe_reclaimable_bytes_sums_safe_items_across_sections() -> None:
    docker = docker_disk(
        images=(image(char="a", size=5 * MB), image(char="b", tags=(), size=3 * MB, dangling=True)),
        build_cache_size=9 * MB,
        build_cache_reclaimable=7 * MB,
    )
    data = report(docker=docker, caches=(cache(kind=CacheKind.UV, size=2 * MB),))

    assert safe_reclaimable_bytes(report=data) == (5 + 3 + 7 + 2) * MB


def test_safe_reclaimable_bytes_leaves_out_every_non_safe_item() -> None:
    docker = docker_disk(
        images=(
            image(char="a", size=MB, in_use=True),
            image(char="b", size=4 * MB, local_build=True),
        ),
        volumes=(volume(name="data", size=9 * MB),),
        containers=(stopped(cid="c", size=6 * MB),),
    )
    data = report(
        docker=docker,
        caches=(cache(kind=CacheKind.TRASH, size=8 * MB),),
        devdirs=(devdir(path="/home/u/p/node_modules", size=11 * MB),),
    )

    assert safe_reclaimable_bytes(report=data) == 0


def test_safe_reclaimable_bytes_counts_a_safe_image_but_not_an_in_use_twin() -> None:
    free = image(char="a", size=5 * MB)
    busy = image(char="b", size=5 * MB, in_use=True)

    assert safe_reclaimable_bytes(report=report(docker=docker_disk(images=(free,)))) == 5 * MB
    assert safe_reclaimable_bytes(report=report(docker=docker_disk(images=(busy,)))) == 0


def test_safe_reclaimable_bytes_ignores_an_unavailable_docker() -> None:
    data = report(
        docker=unavailable_docker(error="daemon down"), caches=(cache(kind=CacheKind.NPM, size=MB),)
    )

    assert safe_reclaimable_bytes(report=data) == MB


def test_safe_reclaimable_bytes_uses_unique_image_size_and_reclaimable_build_cache() -> None:
    docker = docker_disk(
        images=(image(char="a", size=10 * MB, unique_size=4 * MB),),
        build_cache_size=20 * MB,
        build_cache_reclaimable=5 * MB,
    )

    assert safe_reclaimable_bytes(report=report(docker=docker)) == 9 * MB
