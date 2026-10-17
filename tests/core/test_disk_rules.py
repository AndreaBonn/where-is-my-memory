"""Disk report rules on `client.api.df()` fixtures.

The fixtures follow the Docker Engine API `GET /system/df` response (docker-py 5.0.3
`APIClient.df()` returns that JSON unchanged). Field names and types were taken from a
read-only call to the local daemon (Engine 29: Images, Containers, Volumes, BuildCache
with `UsageData` and `InUse`); sizes and names in the files are invented.
"""

from typing import Any

import pytest

from wimm.core.constants import DISK_SECTION_CAP
from wimm.core.disk_rules import (
    build_disk_report,
    filter_devdirs,
    parse_docker_df,
    unavailable_docker,
)
from wimm.model.disk import CacheKind

from .disk_helpers import MB, SCANNED_AT, cache, devdir, load_df, sha


def test_images_classified_in_use_dangling_and_local() -> None:
    docker = parse_docker_df(df=load_df())

    flags = {i.id: (i.in_use, i.dangling, i.local_build) for i in docker.images}

    assert flags[sha("a")] == (True, False, False)  # nginx: one container, has a digest
    assert flags[sha("b")] == (False, False, False)  # python: unused, from a registry
    assert flags[sha("c")] == (False, False, True)  # myapp:dev: no RepoDigests
    assert flags[sha("d")] == (False, True, True)  # untagged, unused
    # Containers == -1 (not computed): the exited container's ImageID still marks it used
    assert flags[sha("e")] == (True, True, True)


def test_images_sorted_by_size_descending_and_tags_drop_none_placeholder() -> None:
    docker = parse_docker_df(df=load_df())

    assert [i.id for i in docker.images] == [sha(c) for c in "cdabe"]
    assert docker.images[0].tags == ("myapp:dev",)
    assert docker.images[1].tags == ()
    assert docker.images[-1].tags == ()  # "<none>:<none>" is not a tag


def test_volumes_orphan_only_when_refcount_zero_unknown_sizes_last() -> None:
    docker = parse_docker_df(df=load_df())

    assert [v.name for v in docker.volumes] == [
        "pgdata",
        "scratch",
        "orphan_small",
        "legacy",
        "nosize",
    ]
    by_name = {v.name: v for v in docker.volumes}
    assert [n for n, v in by_name.items() if v.orphan] == ["scratch", "orphan_small", "nosize"]
    assert by_name["pgdata"].ref_count == 1  # in use: not an orphan
    assert by_name["legacy"].ref_count is None  # UsageData null: unknown, not an orphan
    assert by_name["nosize"].size is None  # Size -1: not computed
    assert by_name["scratch"].size == 120 * MB


def test_stopped_containers_exclude_running_and_paused() -> None:
    docker = parse_docker_df(df=load_df())

    assert [(c.name, c.state, c.size) for c in docker.stopped_containers] == [
        ("old-job", "exited", 2048),
        ("never-started", "created", 0),
    ]


def test_build_cache_total_sums_every_entry() -> None:
    assert parse_docker_df(df=load_df()).build_cache_size == 100 * MB


def test_empty_df_gives_available_docker_with_nothing() -> None:
    docker = parse_docker_df(df=load_df("docker_df_empty.json"))

    assert docker.status.available is True
    assert (docker.images, docker.volumes, docker.stopped_containers) == ((), (), ())
    assert docker.build_cache_size == 0


def test_unavailable_docker_carries_reason_and_no_data() -> None:
    docker = unavailable_docker(error="permission denied on /var/run/docker.sock")

    assert docker.status.available is False
    assert docker.status.error == "permission denied on /var/run/docker.sock"
    assert docker.images == ()


def _many_images(count: int) -> dict[str, Any]:
    images = [
        {
            "Id": f"sha256:{n:064x}",
            "RepoTags": [f"img:{n}"],
            "RepoDigests": [],
            "Containers": 0,
            "Size": n * 1000,
        }
        for n in range(1, count + 1)
    ]
    return {"Images": images, "Containers": [], "Volumes": [], "BuildCache": []}


def test_images_over_cap_keep_the_largest_and_count_the_truncated() -> None:
    docker = parse_docker_df(df=_many_images(DISK_SECTION_CAP + 50))

    assert DISK_SECTION_CAP == 200
    assert len(docker.images) == 200
    assert docker.images_truncated == 50
    assert docker.images[0].size == 250_000
    assert docker.images[-1].size == 51_000


def test_images_at_cap_are_not_truncated() -> None:
    docker = parse_docker_df(df=_many_images(DISK_SECTION_CAP))

    assert (len(docker.images), docker.images_truncated) == (200, 0)


def test_volumes_and_containers_over_cap_count_their_own_truncation() -> None:
    df: dict[str, Any] = {
        "Images": [],
        "Volumes": [
            {"Name": f"v{n}", "UsageData": {"RefCount": 0, "Size": n}} for n in range(1, 206)
        ],
        "Containers": [
            {"Id": f"{n:064x}", "Names": [f"/c{n}"], "State": "exited", "SizeRw": n}
            for n in range(1, 203)
        ],
        "BuildCache": [],
    }

    docker = parse_docker_df(df=df)

    assert (len(docker.volumes), docker.volumes_truncated) == (200, 5)
    assert (len(docker.stopped_containers), docker.containers_truncated) == (200, 2)


def test_filter_devdirs_keeps_only_age_at_or_over_the_minimum() -> None:
    old, edge, young = (
        devdir(path=f"/w/{n}/node_modules", age_days=a)
        for n, a in (("old", 200), ("edge", 90), ("young", 89))
    )

    kept = filter_devdirs(candidates=(old, edge, young), min_age_days=90)

    assert kept == (old, edge)


def test_report_sorts_devdirs_by_size_and_caps_with_counter() -> None:
    dirs = tuple(devdir(path=f"/w/p{n}/node_modules", size=n * MB) for n in range(1, 251))

    result = build_disk_report(
        scanned_at=SCANNED_AT, docker=unavailable_docker(error="x"), caches=(), devdirs=dirs
    )

    assert len(result.devdirs) == 200
    assert result.devdirs_truncated == 50
    assert result.devdirs[0].size == 250 * MB
    assert result.devdirs[-1].size == 51 * MB


def test_report_sorts_caches_by_size_descending() -> None:
    small, big = cache(kind=CacheKind.PIP, size=MB), cache(kind=CacheKind.UV, size=9 * MB)

    result = build_disk_report(
        scanned_at=SCANNED_AT, docker=unavailable_docker(error="x"), caches=(small, big), devdirs=()
    )

    assert [c.kind for c in result.caches] == [CacheKind.UV, CacheKind.PIP]


@pytest.mark.parametrize("field", ["Images", "Containers", "Volumes", "BuildCache"])
def test_df_with_null_section_is_treated_as_empty(field: str) -> None:
    df = load_df()
    df[field] = None

    docker = parse_docker_df(df=df)

    assert docker.status.available is True
