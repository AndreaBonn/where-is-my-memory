"""Planners for disk actions (SPECIFICHE 8.1, 8.2), fed by the disk report. Pure, no I/O.

Mass actions on images and containers (`images_prune_*`, `containers_prune_stopped`) plan
one removal step per id read from the report, so the executor can recheck each one
(decision Q-13, docs/DEVIATIONS.md). `builder_prune` stays a single prune step.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import PurePath
from typing import Protocol

from wimm.core.cache_catalog import withheld_kinds
from wimm.core.cache_titles import CACHE_TITLES
from wimm.i18n import N_, _
from wimm.model.actions import (
    ActionRequest,
    ContainerFingerprint,
    DirFingerprint,
    ImageFingerprint,
)
from wimm.model.disk import CacheEntry, CacheKind, DiskReport, DockerDisk, DockerImage
from wimm.model.enums import ActionKind, Category
from wimm.model.errors import InvalidRequest

from .planning_drafts import Draft, assess_draft, volume_draft
from .planning_tools import CacheToolMissing, no_tool
from .risk import RiskTarget, TargetKind
from .risk_table import devdir_consequence

__all__ = [
    "BUILD_CACHE_ID",
    "DISK_PLANNERS",
    "DiskPlanner",
    "plan_builder_prune",
    "plan_cache_clean",
    "plan_image_remove",
]

TRASH_PHRASE = N_("Cestino")
BUILD_CACHE_ID = "build_cache"
TRUNCATED_NOTE = N_(
    "Il report mostra le {shown} voci più grandi: altre {hidden} restano "
    "e serve una nuova scansione dopo la pulizia."
)


class DiskPlanner(Protocol):
    def __call__(self, *, request: ActionRequest, report: DiskReport | None) -> list[Draft]: ...


def _docker(*, report: DiskReport | None) -> DockerDisk:
    if report is None:
        raise InvalidRequest("Disk report not available yet")
    if not report.docker.status.available:
        raise InvalidRequest(f"Docker not available: {report.docker.status.error}")
    return report.docker


def _image_draft(*, image: DockerImage) -> Draft:
    target = RiskTarget(
        kind="image", has_repo_digests=not image.local_build, dangling=image.dangling
    )
    return Draft(
        owner_ids=frozenset({image.id}),
        kind=ActionKind.IMAGE_REMOVE,
        label=image.tags[0] if image.tags else image.id[:19],
        name=image.id,
        fingerprint=ImageFingerprint(id=image.id),
        assessed=assess_draft(target=target, kind=ActionKind.IMAGE_REMOVE),
        reclaim_ram=0,
        reclaim_disk=image.unique_size,
    )


def plan_image_remove(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    for image in _docker(report=report).images:
        if image.id == request.target_id:
            if image.in_use:
                raise InvalidRequest(f"Image {image.id} is in use by a container")
            return [_image_draft(image=image)]
    raise InvalidRequest(f"Unknown image {request.target_id}")


def _pruned(
    *, request: ActionRequest, drafts: list[Draft], truncated: int, shown: int
) -> list[Draft]:
    """Drop the excluded steps; if the report hides entries, say so in the first step."""
    kept = [d for d in drafts if not d.owner_ids & request.excluded_ids]
    if kept and truncated:
        first = kept[0].assessed
        note = _(TRUNCATED_NOTE).format(shown=shown, hidden=truncated)
        kept[0] = replace(
            kept[0], assessed=replace(first, consequences=(*first.consequences, note))
        )
    return kept


def _plan_prune_images(
    *, request: ActionRequest, report: DiskReport | None, dangling: bool
) -> list[Draft]:
    docker = _docker(report=report)
    drafts = [
        _image_draft(image=i)
        for i in docker.images
        if not i.in_use and (i.dangling or not dangling)
    ]
    shown = len(docker.images)
    return _pruned(request=request, drafts=drafts, truncated=docker.images_truncated, shown=shown)


def _plan_prune_dangling(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    return _plan_prune_images(request=request, report=report, dangling=True)


def _plan_prune_unused(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    return _plan_prune_images(request=request, report=report, dangling=False)


def _plan_prune_containers(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    docker = _docker(report=report)
    target = RiskTarget(kind="container", category=Category.CONTAINER, is_running=False)
    assessed = assess_draft(target=target, kind=ActionKind.CONTAINER_REMOVE)
    drafts = [
        Draft(
            owner_ids=frozenset({c.id}),
            kind=ActionKind.CONTAINER_REMOVE,
            label=c.name,
            name=c.name,
            fingerprint=ContainerFingerprint(id=c.id, status=c.state),
            assessed=assessed,
            reclaim_ram=0,
            reclaim_disk=c.size,
        )
        for c in docker.stopped_containers
    ]
    shown = len(docker.stopped_containers)
    return _pruned(
        request=request, drafts=drafts, truncated=docker.containers_truncated, shown=shown
    )


def plan_builder_prune(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    size = _docker(report=report).build_cache_reclaimable
    if size == 0:
        raise InvalidRequest("Build cache has nothing to reclaim")
    return [
        Draft(
            owner_ids=frozenset({BUILD_CACHE_ID}),
            kind=ActionKind.BUILDER_PRUNE,
            label=_("Build cache"),
            name=_("Build cache"),
            fingerprint=None,
            assessed=assess_draft(
                target=RiskTarget(kind="build_cache"), kind=ActionKind.BUILDER_PRUNE
            ),
            reclaim_ram=0,
            reclaim_disk=size,
        )
    ]


def _plan_volume_remove(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    """Plan a volume removal from the disk report.

    With a report the volume must be listed and an orphan; the executor still rechecks
    that no container mounts it at execution (8.2). Its `CreatedAt` goes into the
    fingerprint, so a volume recreated under the same name is refused; a record without
    it cannot be told apart, so it is not planned, and neither is a volume before the
    first disk scan.
    """
    name = str(request.target_id)
    if report is None:
        raise InvalidRequest(f"No disk report yet, cannot plan the removal of volume {name}")
    for volume in _docker(report=report).volumes:
        if volume.name == name:
            if not volume.orphan:
                raise InvalidRequest(f"Volume {name} is in use or its usage is unknown")
            if not volume.created_at:
                raise InvalidRequest(f"Volume {name} has no known creation time")
            return [
                volume_draft(
                    name=name,
                    kind=request.kind,
                    created_at=volume.created_at,
                    reclaim_disk=volume.size or 0,
                )
            ]
    raise InvalidRequest(f"Unknown volume {name}")


DIR_RISK_KINDS: dict[ActionKind, TargetKind] = {
    ActionKind.CACHE_CLEAN: "cache",
    ActionKind.TRASH_EMPTY: "trash",
    ActionKind.DEVDIR_DELETE: "devdir",
}


def _dir_draft(*, fingerprint: DirFingerprint, size: int, kind: ActionKind, name: str) -> Draft:
    target = RiskTarget(kind=DIR_RISK_KINDS[kind])
    return Draft(
        owner_ids=frozenset({fingerprint.realpath}),
        kind=kind,
        label=fingerprint.realpath,
        name=name,
        fingerprint=fingerprint,
        assessed=assess_draft(target=target, kind=kind),
        reclaim_ram=0,
        reclaim_disk=size,
    )


def _cache_draft(*, entry: CacheEntry | None, kind: ActionKind) -> list[Draft]:
    if entry is None:
        raise InvalidRequest(f"Action {kind.value} has no matching cache in the report")
    fingerprint = DirFingerprint(realpath=entry.path, st_ino=entry.st_ino, st_dev=entry.st_dev)
    name = _(TRASH_PHRASE) if entry.kind is CacheKind.TRASH else entry.path
    draft = _dir_draft(fingerprint=fingerprint, size=entry.size, kind=kind, name=name)
    # F8: the confirmation and the outcome name the cache as the Disco page does.
    draft = replace(draft, label=_(CACHE_TITLES[entry.kind]))
    # The risk depends on what the cache is: maven and the IDE caches are not free to refill.
    target = RiskTarget(kind=DIR_RISK_KINDS[kind], cache_kind=entry.kind)
    return [replace(draft, assessed=assess_draft(target=target, kind=kind))]


def _caches(*, report: DiskReport | None) -> tuple[CacheEntry, ...]:
    if report is None:
        raise InvalidRequest("Disk report not available yet")
    return report.caches


def plan_cache_clean(
    *,
    request: ActionRequest,
    report: DiskReport | None,
    which: Callable[[str], str | None] = no_tool,
) -> list[Draft]:
    entry = next(
        (
            c
            for c in _caches(report=report)
            if c.kind is not CacheKind.TRASH and c.kind.value == request.target_id
        ),
        None,
    )
    if entry is not None and entry.kind in withheld_kinds(which=which):
        raise CacheToolMissing(f"Cache {entry.kind.value} is cleaned only by its own command")
    return _cache_draft(entry=entry, kind=ActionKind.CACHE_CLEAN)


def _plan_trash_empty(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    entry = next((c for c in _caches(report=report) if c.kind is CacheKind.TRASH), None)
    return _cache_draft(entry=entry, kind=ActionKind.TRASH_EMPTY)


def _plan_devdir_delete(*, request: ActionRequest, report: DiskReport | None) -> list[Draft]:
    if report is None:
        raise InvalidRequest("Disk report not available yet")
    for item in report.devdirs:
        if item.path == request.target_id:
            fingerprint = DirFingerprint(realpath=item.path, st_ino=item.st_ino, st_dev=item.st_dev)
            draft = _dir_draft(
                fingerprint=fingerprint,
                size=item.size,
                kind=ActionKind.DEVDIR_DELETE,
                name=item.path,
            )
            text = devdir_consequence(folder_name=PurePath(item.path).name, marker=item.marker)
            assessed = replace(draft.assessed, consequences=(text,))
            return [replace(draft, assessed=assessed)]
    raise InvalidRequest(f"Unknown development folder {request.target_id}")


DISK_PLANNERS: dict[ActionKind, DiskPlanner] = {
    ActionKind.IMAGE_REMOVE: plan_image_remove,
    ActionKind.IMAGES_PRUNE_DANGLING: _plan_prune_dangling,
    ActionKind.IMAGES_PRUNE_UNUSED: _plan_prune_unused,
    ActionKind.CONTAINERS_PRUNE_STOPPED: _plan_prune_containers,
    ActionKind.BUILDER_PRUNE: plan_builder_prune,
    ActionKind.VOLUME_REMOVE: _plan_volume_remove,
    ActionKind.TRASH_EMPTY: _plan_trash_empty,
    ActionKind.DEVDIR_DELETE: _plan_devdir_delete,
}
