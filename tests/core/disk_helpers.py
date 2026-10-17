import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from wimm.model.disk import (
    CacheEntry,
    CacheKind,
    DevDir,
    DiskReport,
    DockerDisk,
    DockerImage,
    DockerVolume,
    StoppedContainer,
)
from wimm.model.snapshot import DockerStatus

FIXTURES = Path(__file__).parents[1] / "fixtures"
SCANNED_AT = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
MB = 1_000_000


def load_df(name: str = "docker_df.json") -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def sha(char: str) -> str:
    return "sha256:" + char * 64


def image(
    *,
    char: str,
    tags: tuple[str, ...] = ("app:1",),
    size: int = 10 * MB,
    in_use: bool = False,
    dangling: bool = False,
    local_build: bool = False,
) -> DockerImage:
    return DockerImage(
        id=sha(char),
        tags=tags,
        size=size,
        in_use=in_use,
        dangling=dangling,
        local_build=local_build,
    )


def volume(*, name: str, ref_count: int | None = 0, size: int | None = MB) -> DockerVolume:
    return DockerVolume(name=name, size=size, ref_count=ref_count)


def stopped(*, cid: str, state: str = "exited", size: int = 1024) -> StoppedContainer:
    return StoppedContainer(id=cid * 64, name=f"ctr-{cid}", state=state, size=size)


def docker_disk(
    *,
    images: tuple[DockerImage, ...] = (),
    volumes: tuple[DockerVolume, ...] = (),
    containers: tuple[StoppedContainer, ...] = (),
    build_cache_size: int = 0,
    images_truncated: int = 0,
    containers_truncated: int = 0,
) -> DockerDisk:
    return DockerDisk(
        status=DockerStatus(available=True, error=None),
        images=images,
        volumes=volumes,
        stopped_containers=containers,
        build_cache_size=build_cache_size,
        images_truncated=images_truncated,
        containers_truncated=containers_truncated,
    )


def cache(*, kind: CacheKind, size: int = MB, ino: int = 11, dev: int = 2049) -> CacheEntry:
    return CacheEntry(
        kind=kind, path=f"/home/u/.cache/{kind.value}", size=size, st_ino=ino, st_dev=dev
    )


def devdir(*, path: str, size: int = MB, age_days: int = 120) -> DevDir:
    return DevDir(path=path, size=size, age_days=age_days, st_ino=77, st_dev=2049)


def report(
    *,
    docker: DockerDisk | None = None,
    caches: tuple[CacheEntry, ...] = (),
    devdirs: tuple[DevDir, ...] = (),
) -> DiskReport:
    return DiskReport(
        scanned_at=SCANNED_AT,
        docker=docker or docker_disk(),
        caches=caches,
        devdirs=devdirs,
    )
