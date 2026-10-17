"""Pure disk report rules (SPECIFICHE 7.6): classify `docker df`, sort and cap sections.

The `df` input is the JSON of the Docker Engine `GET /system/df` call, which docker-py
5.0.3 returns unchanged from `client.api.df()`. No I/O happens here.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

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
from wimm.model.enums import ActionKind, Risk
from wimm.model.snapshot import DockerStatus

from .constants import DISK_SECTION_CAP
from .risk import RiskTarget, assess_risk

__all__ = [
    "build_disk_report",
    "filter_devdirs",
    "parse_docker_df",
    "safe_reclaimable_bytes",
    "unavailable_docker",
]

NONE_TAG = "<none>:<none>"
NONE_DIGEST = "<none>@<none>"
# Docker reports -1 for a figure it did not compute.
NOT_COMPUTED = -1
STOPPED_STATES = frozenset({"exited", "created", "dead"})

type Raw = Mapping[str, Any]


def _entries(*, df: Raw, key: str) -> list[Raw]:
    """The df lists are `null` when empty."""
    value = df.get(key)
    return list(value) if value else []


def _size(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


def _top[T](
    *, items: Iterable[T], key: Callable[[T], tuple[Any, ...]]
) -> tuple[tuple[T, ...], int]:
    ordered = sorted(items, key=key)
    return tuple(ordered[:DISK_SECTION_CAP]), max(len(ordered) - DISK_SECTION_CAP, 0)


def _image(*, raw: Raw, used_ids: frozenset[str]) -> DockerImage:
    image_id = str(raw["Id"])
    tags = tuple(tag for tag in raw.get("RepoTags") or [] if tag != NONE_TAG)
    digests = [digest for digest in raw.get("RepoDigests") or [] if digest != NONE_DIGEST]
    # `Containers` is -1 when the daemon did not count; the containers list decides then.
    counted = raw.get("Containers")
    in_use = (type(counted) is int and counted > 0) or image_id in used_ids
    return DockerImage(
        id=image_id,
        tags=tags,
        size=_size(raw.get("Size")),
        in_use=in_use,
        dangling=not tags,
        local_build=not digests,
    )


def _volume(*, raw: Raw) -> DockerVolume:
    usage = raw.get("UsageData") or {}
    size, refs = usage.get("Size"), usage.get("RefCount")
    return DockerVolume(
        name=str(raw["Name"]),
        size=size if type(size) is int and size >= 0 else None,
        ref_count=refs if type(refs) is int and refs >= 0 else None,
    )


def _stopped(*, raw: Raw) -> StoppedContainer:
    cid = str(raw["Id"])
    names = raw.get("Names") or []
    return StoppedContainer(
        id=cid,
        name=str(names[0]).lstrip("/") if names else cid[:12],
        state=str(raw["State"]),
        size=_size(raw.get("SizeRw")),
    )


def _capped_images(*, df: Raw, containers: list[Raw]) -> tuple[tuple[DockerImage, ...], int]:
    used_ids = frozenset(str(c["ImageID"]) for c in containers if c.get("ImageID"))
    images = (_image(raw=r, used_ids=used_ids) for r in _entries(df=df, key="Images"))
    return _top(items=images, key=lambda i: (-i.size, i.id))


def _capped_volumes(*, df: Raw) -> tuple[tuple[DockerVolume, ...], int]:
    volumes = (_volume(raw=r) for r in _entries(df=df, key="Volumes"))
    return _top(items=volumes, key=lambda v: (v.size is None, -(v.size or 0), v.name))


def _capped_stopped(*, containers: list[Raw]) -> tuple[tuple[StoppedContainer, ...], int]:
    stopped = (_stopped(raw=c) for c in containers if c.get("State") in STOPPED_STATES)
    return _top(items=stopped, key=lambda c: (-c.size, c.id))


def parse_docker_df(*, df: Raw) -> DockerDisk:
    """Classify a `docker df` answer.

    An image is in use if a container, even a stopped one, references it; dangling if it
    has no tag (`RepoTags` empty or only `<none>:<none>`); a local build if it has no
    `RepoDigests`. A volume is an orphan when `UsageData.RefCount == 0`. Stopped
    containers are those exited, created or dead. Every section is sorted by size,
    descending, and capped at `DISK_SECTION_CAP` with a counter of the hidden ones.
    Image and volume sizes are upper bounds: layers shared with other images are counted
    in full.
    """
    containers = _entries(df=df, key="Containers")
    images, images_cut = _capped_images(df=df, containers=containers)
    volumes, volumes_cut = _capped_volumes(df=df)
    stopped, stopped_cut = _capped_stopped(containers=containers)
    return DockerDisk(
        status=DockerStatus(available=True, error=None),
        images=images,
        volumes=volumes,
        stopped_containers=stopped,
        build_cache_size=sum(_size(r.get("Size")) for r in _entries(df=df, key="BuildCache")),
        images_truncated=images_cut,
        volumes_truncated=volumes_cut,
        containers_truncated=stopped_cut,
    )


def unavailable_docker(*, error: str) -> DockerDisk:
    """The Docker part when the daemon cannot be reached: no data, the reason kept."""
    return DockerDisk(
        status=DockerStatus(available=False, error=error),
        images=(),
        volumes=(),
        stopped_containers=(),
        build_cache_size=0,
    )


def filter_devdirs(*, candidates: Iterable[DevDir], min_age_days: int) -> tuple[DevDir, ...]:
    """Keep the directories whose project is at least `min_age_days` old (whole days)."""
    return tuple(d for d in candidates if d.age_days >= min_age_days)


def build_disk_report(
    *,
    scanned_at: datetime,
    docker: DockerDisk,
    caches: Iterable[CacheEntry],
    devdirs: Iterable[DevDir],
) -> DiskReport:
    """Assemble the report: caches and dev directories by size, dev directories capped."""
    kept, cut = _top(items=devdirs, key=lambda d: (-d.size, d.path))
    return DiskReport(
        scanned_at=scanned_at,
        docker=docker,
        caches=tuple(sorted(caches, key=lambda c: (-c.size, c.kind.value))),
        devdirs=kept,
        devdirs_truncated=cut,
    )


def _is_safe(*, target: RiskTarget, action: ActionKind) -> bool:
    """The risk the planner assigns to this target: one rule for the plan and the total."""
    return assess_risk(target=target, action=action).level is Risk.SAFE


def _safe_image_bytes(*, docker: DockerDisk) -> int:
    total = 0
    for item in docker.images:
        target = RiskTarget(
            kind="image", has_repo_digests=not item.local_build, dangling=item.dangling
        )
        if not item.in_use and _is_safe(target=target, action=ActionKind.IMAGE_REMOVE):
            total += item.size
    return total


def safe_reclaimable_bytes(*, report: DiskReport | None) -> int:
    """Bytes of the report's items whose removal is rated `safe`; 0 before the first scan.

    Same ratings as the planner (decision Q-6): caches except the trash, the build cache
    and the images no container uses (dangling, or pullable again). Stopped containers,
    volumes, development folders and the trash are never counted.
    """
    if report is None:
        return 0
    cache_ok = _is_safe(target=RiskTarget(kind="cache"), action=ActionKind.CACHE_CLEAN)
    trash_ok = _is_safe(target=RiskTarget(kind="trash"), action=ActionKind.TRASH_EMPTY)
    total = sum(
        entry.size
        for entry in report.caches
        if (trash_ok if entry.kind is CacheKind.TRASH else cache_ok)
    )
    build_ok = _is_safe(target=RiskTarget(kind="build_cache"), action=ActionKind.BUILDER_PRUNE)
    return (
        total
        + _safe_image_bytes(docker=report.docker)
        + (report.docker.build_cache_size if build_ok else 0)
    )
