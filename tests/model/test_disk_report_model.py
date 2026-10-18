from dataclasses import replace
from datetime import datetime

import pytest

from tests.core.disk_helpers import cache, devdir, docker_disk, image, report, volume
from tests.helpers import invalid_model_value
from wimm.model.disk import CacheKind, DiskReport, DockerDisk, DockerImage, DockerVolume
from wimm.model.snapshot import DockerStatus


def test_orphan_is_refcount_zero_only() -> None:
    assert volume(name="a", ref_count=0).orphan is True
    assert volume(name="b", ref_count=2).orphan is False
    assert volume(name="c", ref_count=None).orphan is False


@pytest.mark.parametrize("size", [-1, 1.5, True])
def test_image_size_must_be_a_nonnegative_integer(size: object) -> None:
    with pytest.raises(ValueError, match="size"):
        replace(image(char="a"), size=invalid_model_value(size))


def test_image_unique_size_is_bounded_by_size() -> None:
    assert replace(image(char="a", size=10), unique_size=10).unique_size == 10
    assert replace(image(char="a", size=10), unique_size=0).unique_size == 0
    with pytest.raises(ValueError, match="unique_size"):
        replace(image(char="a", size=10), unique_size=11)
    with pytest.raises(ValueError, match="unique_size"):
        replace(image(char="a", size=10), unique_size=-1)


def test_build_cache_reclaimable_is_bounded_by_the_total() -> None:
    assert docker_disk(build_cache_size=10, build_cache_reclaimable=10)
    assert docker_disk(build_cache_size=10, build_cache_reclaimable=0)
    with pytest.raises(ValueError, match="build_cache_reclaimable"):
        docker_disk(build_cache_size=10, build_cache_reclaimable=11)
    with pytest.raises(ValueError, match="build_cache_reclaimable"):
        docker_disk(build_cache_size=10, build_cache_reclaimable=-1)


def test_image_tags_must_be_a_tuple() -> None:
    with pytest.raises(ValueError, match="tags"):
        replace(image(char="a"), tags=invalid_model_value(["x:1"]))


def test_image_id_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="id"):
        DockerImage(
            id=" ", tags=(), size=0, unique_size=0, in_use=False, dangling=True, local_build=True
        )


def test_volume_size_none_allowed_but_negative_rejected() -> None:
    assert DockerVolume(name="v", size=None, ref_count=None, created_at="").size is None
    with pytest.raises(ValueError, match="size"):
        DockerVolume(name="v", size=-1, ref_count=0, created_at="")


@pytest.mark.parametrize(("tags", "dangling"), [(("app:1",), True), ((), False)])
def test_image_dangling_flag_must_match_the_tags(tags: tuple[str, ...], dangling: bool) -> None:
    with pytest.raises(ValueError, match="dangling"):
        DockerImage(
            id="sha256:a",
            tags=tags,
            size=0,
            unique_size=0,
            in_use=False,
            dangling=dangling,
            local_build=False,
        )


def test_docker_images_must_have_unique_ids() -> None:
    with pytest.raises(ValueError, match="unique"):
        docker_disk(images=(image(char="a"), image(char="a")))


def test_unavailable_docker_must_be_empty() -> None:
    status = DockerStatus(available=False, error="down")
    assert DockerDisk(
        status=status,
        images=(),
        volumes=(),
        stopped_containers=(),
        build_cache_size=0,
        build_cache_reclaimable=0,
    )
    with pytest.raises(ValueError, match="unavailable"):
        DockerDisk(
            status=status,
            images=(image(char="a"),),
            volumes=(),
            stopped_containers=(),
            build_cache_size=0,
            build_cache_reclaimable=0,
        )


def test_truncation_counters_must_be_nonnegative() -> None:
    with pytest.raises(ValueError, match="devdirs_truncated"):
        replace(report(), devdirs_truncated=-1)


def test_report_requires_aware_scan_time() -> None:
    with pytest.raises(ValueError, match="scanned_at"):
        DiskReport(
            scanned_at=datetime(2026, 10, 16, 12, 0),
            docker=docker_disk(),
            caches=(),
            devdirs=(),
        )


def test_cache_and_devdir_reject_negative_numbers() -> None:
    with pytest.raises(ValueError, match="size"):
        replace(cache(kind=CacheKind.UV), size=-5)
    with pytest.raises(ValueError, match="age_days"):
        replace(devdir(path="/w/node_modules"), age_days=-1)
    with pytest.raises(ValueError, match="st_ino"):
        replace(devdir(path="/w/node_modules"), st_ino=-1)


def test_cache_kinds_cover_the_spec_list() -> None:
    assert {k.value for k in CacheKind} == {
        "uv",
        "npm",
        "pip",
        "thumbnails",
        "trash",
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
    }


def test_devdir_marker_defaults_to_empty_and_must_be_text() -> None:
    assert devdir(path="/w/node_modules").marker == ""
    with pytest.raises(ValueError, match="marker"):
        replace(devdir(path="/w/target"), marker=invalid_model_value(3))
