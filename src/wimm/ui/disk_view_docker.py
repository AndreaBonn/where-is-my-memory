"""Docker sections of the Disco page: images, stopped containers, volumes, build cache."""

from dataclasses import replace

from wimm.core.risk import RiskTarget
from wimm.model.disk import DiskReport, DockerDisk, DockerImage, DockerVolume, StoppedContainer
from wimm.model.enums import ActionKind
from wimm.ui.disk_model import (
    ActionSpec,
    DiskRowView,
    DiskSectionView,
    SectionActionView,
    make_row,
    more_text,
)
from wimm.ui.format import button_label, format_size

UNNAMED_IMAGE_TEXT = "Immagine senza nome"
SHORT_ID_CHARS = 12
DOCKER_KEY = "docker"


def _image_row(*, image: DockerImage) -> DiskRowView:
    states = ["in uso da un container" if image.in_use else "non in uso"]
    if image.dangling:
        states.append("senza nome")
    if image.local_build:
        states.append("costruita in locale")
    if not image.tags:
        # D5: nobody says a digest out loud; it stays at the end for who needs it.
        states.append("id " + image.id.removeprefix("sha256:")[:SHORT_ID_CHARS])
    target = RiskTarget(
        kind="image", has_repo_digests=not image.local_build, dangling=image.dangling
    )
    action = None if image.in_use else ActionSpec(ActionKind.IMAGE_REMOVE, target, image.id)
    return make_row(
        title=image.tags[0] if image.tags else UNNAMED_IMAGE_TEXT,
        subtitle=" · ".join(states),
        size=image.unique_size,
        action=action,
    )


def _container_row(*, container: StoppedContainer) -> DiskRowView:
    target = RiskTarget(kind="container", is_running=False)
    return make_row(
        title=container.name,
        subtitle="fermo",
        size=container.size,
        action=ActionSpec(ActionKind.CONTAINER_REMOVE, target, container.id),
    )


def _volume_state(*, volume: DockerVolume) -> tuple[str, bool]:
    """The state text and whether the volume can be removed from here."""
    if volume.ref_count is None:
        return "non sappiamo se un contenitore lo usa", False
    if not volume.orphan:
        return "in uso da un container", False
    if not volume.created_at:
        return "non rimovibile: data di creazione non nota", False
    return "non usato", True


def _volume_row(*, volume: DockerVolume) -> DiskRowView:
    state, removable = _volume_state(volume=volume)
    action = ActionSpec(ActionKind.VOLUME_REMOVE, RiskTarget(kind="volume"), volume.name)
    return make_row(
        title=volume.name,
        subtitle=state,
        size=volume.size,
        action=action if removable else None,
    )


def _build_cache_row(*, docker: DockerDisk) -> DiskRowView:
    reclaimable = docker.build_cache_reclaimable
    action = ActionSpec(ActionKind.BUILDER_PRUNE, RiskTarget(kind="build_cache"), None)
    row = make_row(
        title="Cache di build",
        subtitle=f"liberabili {format_size(size=reclaimable)}",
        size=docker.build_cache_size,
        action=action if reclaimable else None,
    )
    # The prune frees only the reclaimable part: that is what the headline may count.
    return replace(row, size_bytes=reclaimable)


def _prune_action(*, kind: ActionKind) -> SectionActionView:
    return SectionActionView(kind=kind, label=button_label(kind=kind))


def _image_actions(*, images: tuple[DockerImage, ...]) -> tuple[SectionActionView, ...]:
    """Prune buttons for the images that have candidates; the unused one only if it adds some."""
    unused = [i for i in images if not i.in_use]
    dangling = [i for i in unused if i.dangling]
    actions = []
    if dangling:
        actions.append(_prune_action(kind=ActionKind.IMAGES_PRUNE_DANGLING))
    if len(unused) > len(dangling):
        actions.append(_prune_action(kind=ActionKind.IMAGES_PRUNE_UNUSED))
    return tuple(actions)


def _container_actions(*, docker: DockerDisk) -> tuple[SectionActionView, ...]:
    if not docker.stopped_containers:
        return ()
    return (_prune_action(kind=ActionKind.CONTAINERS_PRUNE_STOPPED),)


def docker_sections(*, report: DiskReport) -> tuple[DiskSectionView, ...]:
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
