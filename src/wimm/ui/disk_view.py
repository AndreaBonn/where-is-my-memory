"""Pure view model of the Disco page: a disk report in, sections with rows out."""

from dataclasses import dataclass
from datetime import datetime

from wimm.core.constants import DISK_SECTION_CAP
from wimm.core.risk import RiskTarget, assess_risk
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
from wimm.ui.format import RISK_STYLE, RISK_TEXT, button_label, format_clock, format_size

NO_SCAN_TEXT = "Nessuna scansione ancora"
UNKNOWN_SIZE_TEXT = "dimensione non nota"
DOCKER_KEY = "docker"
CACHE_TITLES = {
    CacheKind.UV: "uv",
    CacheKind.NPM: "npm",
    CacheKind.PIP: "pip",
    CacheKind.THUMBNAILS: "Miniature",
    CacheKind.TRASH: "Cestino",
}


@dataclass(frozen=True, slots=True)
class DiskRowView:
    """One row; `action_kind` and `target_id` let the page build the action request later."""

    title: str
    subtitle: str
    size_text: str
    risk: Risk | None = None
    risk_text: str | None = None
    risk_style: str | None = None
    action_kind: ActionKind | None = None
    target_id: str | None = None


@dataclass(frozen=True, slots=True)
class SectionActionView:
    """A mass action of a section (RF-22); its label already carries the confirm ellipsis."""

    kind: ActionKind
    label: str


@dataclass(frozen=True, slots=True)
class DiskSectionView:
    key: str
    title: str
    rows: tuple[DiskRowView, ...] = ()
    more_text: str | None = None
    message: str | None = None
    actions: tuple[SectionActionView, ...] = ()


def more_text(*, count: int) -> str | None:
    """The "e altre N" counter for rows a cap hid; None when nothing is hidden."""
    if count <= 0:
        return None
    return "e altre " + f"{count:,}".replace(",", ".")


def last_scan_text(*, report: DiskReport | None, now: datetime) -> str:
    """The header line: local time of the last scan, or the no-scan text."""
    if report is None:
        return NO_SCAN_TEXT
    return f"Ultima scansione: {format_clock(value=report.scanned_at, now=now)}"


@dataclass(frozen=True, slots=True)
class _Action:
    """What a row can do: the planner's risk target, the action and the id it acts on."""

    kind: ActionKind
    target: RiskTarget
    target_id: str | None


def _row(*, title: str, subtitle: str, size: int | None, action: _Action | None) -> DiskRowView:
    """Build a row; the badge comes from the planner's own assessment, no action = no badge."""
    size_text = UNKNOWN_SIZE_TEXT if size is None else format_size(size=size)
    if action is None:
        return DiskRowView(title=title, subtitle=subtitle, size_text=size_text)
    level: Risk = assess_risk(target=action.target, action=action.kind).level
    return DiskRowView(
        title=title,
        subtitle=subtitle,
        size_text=size_text,
        risk=level,
        risk_text=RISK_TEXT[level],
        risk_style=RISK_STYLE[level],
        action_kind=action.kind,
        target_id=action.target_id,
    )


def _image_row(*, image: DockerImage) -> DiskRowView:
    states = ["in uso da un container" if image.in_use else "non in uso"]
    if image.dangling:
        states.append("senza nome")
    if image.local_build:
        states.append("costruita in locale")
    target = RiskTarget(
        kind="image", has_repo_digests=not image.local_build, dangling=image.dangling
    )
    action = None if image.in_use else _Action(ActionKind.IMAGE_REMOVE, target, image.id)
    return _row(
        title=image.tags[0] if image.tags else image.id[:19],
        subtitle=" · ".join(states),
        size=image.unique_size,
        action=action,
    )


def _container_row(*, container: StoppedContainer) -> DiskRowView:
    target = RiskTarget(kind="container", is_running=False)
    return _row(
        title=container.name,
        subtitle=f"fermo ({container.state})",
        size=container.size,
        action=_Action(ActionKind.CONTAINER_REMOVE, target, container.id),
    )


def _volume_state(*, volume: DockerVolume) -> tuple[str, bool]:
    """The state text and whether the volume can be removed from here."""
    if volume.ref_count is None:
        return "uso non noto", False
    if not volume.orphan:
        return "in uso da un container", False
    if not volume.created_at:
        return "non rimovibile: data di creazione non nota", False
    return "non usato", True


def _volume_row(*, volume: DockerVolume) -> DiskRowView:
    state, removable = _volume_state(volume=volume)
    action = _Action(ActionKind.VOLUME_REMOVE, RiskTarget(kind="volume"), volume.name)
    return _row(
        title=volume.name,
        subtitle=state,
        size=volume.size,
        action=action if removable else None,
    )


def _cache_row(*, entry: CacheEntry) -> DiskRowView:
    trash = entry.kind is CacheKind.TRASH
    action = _Action(
        kind=ActionKind.TRASH_EMPTY if trash else ActionKind.CACHE_CLEAN,
        target=RiskTarget(kind="trash" if trash else "cache"),
        # trash_empty takes no target (the planner finds the trash); a cache is named by kind.
        target_id=None if trash else entry.kind.value,
    )
    return _row(title=CACHE_TITLES[entry.kind], subtitle=entry.path, size=entry.size, action=action)


def _devdir_row(*, item: DevDir) -> DiskRowView:
    action = _Action(ActionKind.DEVDIR_DELETE, RiskTarget(kind="devdir"), item.path)
    return _row(
        title=item.path,
        subtitle=f"progetto fermo da {item.age_days} giorni",
        size=item.size,
        action=action,
    )


def _build_cache_row(*, docker: DockerDisk) -> DiskRowView:
    reclaimable = docker.build_cache_reclaimable
    action = _Action(ActionKind.BUILDER_PRUNE, RiskTarget(kind="build_cache"), None)
    return _row(
        title="Cache di build",
        subtitle=f"liberabili {format_size(size=reclaimable)}",
        size=docker.build_cache_size,
        action=action if reclaimable else None,
    )


def _image_level(*, image: DockerImage) -> Risk:
    target = RiskTarget(
        kind="image", has_repo_digests=not image.local_build, dangling=image.dangling
    )
    return assess_risk(target=target, action=ActionKind.IMAGE_REMOVE).level


def _prune_action(*, kind: ActionKind, level: Risk) -> SectionActionView:
    return SectionActionView(kind=kind, label=button_label(kind=kind, risk=level))


def _image_actions(*, images: tuple[DockerImage, ...]) -> tuple[SectionActionView, ...]:
    """Prune buttons for the images that have candidates; the unused one only if it adds some."""
    unused = [i for i in images if not i.in_use]
    dangling = [i for i in unused if i.dangling]
    actions = []
    if dangling:
        level = max(_image_level(image=i) for i in dangling)
        actions.append(_prune_action(kind=ActionKind.IMAGES_PRUNE_DANGLING, level=level))
    if len(unused) > len(dangling):
        level = max(_image_level(image=i) for i in unused)
        actions.append(_prune_action(kind=ActionKind.IMAGES_PRUNE_UNUSED, level=level))
    return tuple(actions)


def _container_actions(*, docker: DockerDisk) -> tuple[SectionActionView, ...]:
    if not docker.stopped_containers:
        return ()
    level = assess_risk(
        target=RiskTarget(kind="container", is_running=False), action=ActionKind.CONTAINER_REMOVE
    ).level
    return (_prune_action(kind=ActionKind.CONTAINERS_PRUNE_STOPPED, level=level),)


def _capped(*, rows: tuple[DiskRowView, ...], hidden: int) -> tuple[tuple[DiskRowView, ...], int]:
    shown = rows[:DISK_SECTION_CAP]
    return shown, hidden + len(rows) - len(shown)


def _docker_sections(*, report: DiskReport) -> tuple[DiskSectionView, ...]:
    docker = report.docker
    if not docker.status.available:
        message = f"Docker non disponibile: {docker.status.error}"
        return (DiskSectionView(key=DOCKER_KEY, title="Docker", message=message),)
    images = tuple(_image_row(image=i) for i in docker.images)
    containers = tuple(_container_row(container=c) for c in docker.stopped_containers)
    volumes = tuple(_volume_row(volume=v) for v in docker.volumes)
    return (
        DiskSectionView(
            "images",
            "Immagini Docker",
            images,
            more_text(count=docker.images_truncated),
            actions=_image_actions(images=docker.images),
        ),
        DiskSectionView(
            "containers",
            "Container fermi",
            containers,
            more_text(count=docker.containers_truncated),
            actions=_container_actions(docker=docker),
        ),
        DiskSectionView(
            "volumes", "Volumi Docker", volumes, more_text(count=docker.volumes_truncated)
        ),
        DiskSectionView("build_cache", "Cache di build Docker", (_build_cache_row(docker=docker),)),
    )


def _listed(*, key: str, title: str, rows: tuple[DiskRowView, ...], empty: str) -> DiskSectionView:
    return DiskSectionView(key=key, title=title, rows=rows, message=None if rows else empty)


def _devdirs_section(*, report: DiskReport, min_age_days: int) -> DiskSectionView:
    largest_first = sorted(report.devdirs, key=lambda d: -d.size)
    dirs = tuple(_devdir_row(item=d) for d in largest_first)
    shown, hidden = _capped(rows=dirs, hidden=report.devdirs_truncated)
    empty = (
        f"Nessuna cartella di dipendenze più vecchia di {min_age_days} giorni "
        "nelle radici configurate"
    )
    return DiskSectionView(
        "devdirs",
        "Cartelle di dipendenze",
        shown,
        more_text(count=hidden),
        None if shown else empty,
    )


def _local_sections(*, report: DiskReport, min_age_days: int) -> tuple[DiskSectionView, ...]:
    caches = tuple(_cache_row(entry=e) for e in report.caches if e.kind is not CacheKind.TRASH)
    trash = tuple(_cache_row(entry=e) for e in report.caches if e.kind is CacheKind.TRASH)
    return (
        _listed(key="caches", title="Cache", rows=caches, empty="Nessuna cache trovata"),
        _devdirs_section(report=report, min_age_days=min_age_days),
        _listed(key="trash", title="Cestino", rows=trash, empty="Cestino non rilevato"),
    )


def build_disk_sections(
    *, report: DiskReport | None, min_age_days: int
) -> tuple[DiskSectionView, ...]:
    """All sections of the page; empty before the first scan."""
    if report is None:
        return ()
    return _docker_sections(report=report) + _local_sections(
        report=report, min_age_days=min_age_days
    )
