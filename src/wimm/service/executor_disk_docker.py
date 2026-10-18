"""Docker disk steps (SPECIFICHE 8.2, 8.4): image, volume and build cache removal."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from wimm.model.actions import (
    DirFingerprint,
    ImageFingerprint,
    Plan,
    PlanStep,
    VolumeFingerprint,
)
from wimm.model.enums import ActionKind

from .control_protocols import (
    DockerControl,
    LiveImage,
    StepOutcome,
    StepStatus,
    failed_outcome,
)
from .errors import ControlFailed, InvalidRequest, TargetChanged, TargetGone, WimmError
from .executor_disk_fs import DISK_FS_KINDS

LOGGER = logging.getLogger(__name__)
DISK_DOCKER_KINDS = frozenset(
    {ActionKind.IMAGE_REMOVE, ActionKind.VOLUME_REMOVE, ActionKind.BUILDER_PRUNE}
)
UNKNOWN_BYTES = "unknown"


@dataclass(frozen=True, slots=True)
class ImageRemoval:
    """What an image removal did: `changed` if something was removed by this step."""

    changed: bool
    note: str | None = None


def _live_image(*, step: PlanStep, control: DockerControl) -> LiveImage | None:
    """The live image for an image step, None if gone; raise if in use, replaced or a parent."""
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ImageFingerprint):
        raise InvalidRequest(f"Step {step.order} has no image fingerprint")
    image = control.inspect_image(image_id=fingerprint.id)
    if image is None:
        return None
    if image.id != fingerprint.id or image.in_use:
        raise TargetChanged(f"Image {fingerprint.id[:19]} is in use or was replaced")
    if image.has_children:
        raise TargetChanged(f"Image {fingerprint.id[:19]} has child images, nothing was untagged")
    return image


def _volume_fingerprint(*, step: PlanStep) -> VolumeFingerprint:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, VolumeFingerprint):
        raise InvalidRequest(f"Step {step.order} has no volume fingerprint")
    return fingerprint


def _present(*, step: PlanStep, control: DockerControl) -> bool:
    """True if the target is there and still removable, False if gone; raise if it changed.

    An image or volume that a container (even a stopped one) now uses is `TargetChanged`:
    nothing is removed. So is a volume recreated under the same name, or one whose
    creation time is unknown on either side. The build cache has no identity.
    """
    if step.kind is ActionKind.BUILDER_PRUNE:
        return True
    if step.kind is ActionKind.IMAGE_REMOVE:
        return _live_image(step=step, control=control) is not None
    fingerprint = _volume_fingerprint(step=step)
    volume = control.inspect_volume(name=fingerprint.name)
    if volume is None:
        return False
    if volume.in_use:
        raise TargetChanged(f"Volume {fingerprint.name} is now used by a container")
    if not _same_instant(planned=fingerprint.created_at, live=volume.created_at):
        raise TargetChanged(
            f"Volume {fingerprint.name} was recreated or its creation time is unknown"
        )
    return True


def _same_instant(*, planned: str, live: str) -> bool:
    """Equal creation times, compared as instants: df and inspect may format them apart.

    An empty or unparsable value on either side is never equal, so the removal is refused.
    """
    try:
        return datetime.fromisoformat(planned) == datetime.fromisoformat(live)
    except ValueError:
        return False


def _untag(*, control: DockerControl, image: LiveImage) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Untag every tag that still points at the image; return (removed, moved elsewhere).

    A tag is re-resolved right before its removal: one that now points to another image
    is left alone and reported, never removed.
    """
    removed: list[str] = []
    moved: list[str] = []
    for tag in image.tags:
        current = control.resolve_image(ref=tag)
        if current is None:
            continue
        if current != image.id:
            moved.append(tag)
            continue
        try:
            control.remove_image(ref=tag)
        except TargetGone:
            continue
        except WimmError as error:
            raise ControlFailed(
                f"{error.message} (tags already removed: {_listed(removed)})"
            ) from error
        removed.append(tag)
    return tuple(removed), tuple(moved)


def _listed(names: Sequence[str]) -> str:
    return ", ".join(names) or "none"


def _remove_image(*, control: DockerControl, image: LiveImage) -> ImageRemoval:
    """Untag each tag, then remove by id if it still exists.

    Removing an id that carries several tags is refused by the daemon (409) and `force` is
    never used, so the tags go first. A failure reports the tags already gone.
    """
    removed, moved = _untag(control=control, image=image)
    note = f"tags left alone, now on another image: {_listed(moved)}" if moved else None
    if control.inspect_image(image_id=image.id) is None:
        return ImageRemoval(changed=bool(removed), note=note)
    try:
        control.remove_image(ref=image.id)
    except TargetGone:
        return ImageRemoval(changed=bool(removed), note=note)
    except WimmError as error:
        raise ControlFailed(
            f"{error.message} (tags already removed: {_listed(removed)})"
        ) from error
    return ImageRemoval(changed=True, note=note)


def check_disk_docker(*, step: PlanStep, control: DockerControl) -> None:
    """Reject the plan if an image or volume is now in use; a vanished one is fine."""
    _present(step=step, control=control)


def _run_image_step(*, control: DockerControl, step: PlanStep) -> StepOutcome:
    image = _live_image(step=step, control=control)
    if image is None:
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    removal = _remove_image(control=control, image=image)
    status = StepStatus.DONE if removal.changed else StepStatus.ALREADY_GONE
    return StepOutcome(order=step.order, status=status, message=removal.note)


def _run_volume_step(*, control: DockerControl, step: PlanStep) -> StepOutcome:
    if not _present(step=step, control=control):
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    try:
        control.remove_volume(name=_volume_fingerprint(step=step).name)
    except TargetGone:
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    return StepOutcome(order=step.order, status=StepStatus.DONE)


def run_disk_docker_step(*, control: DockerControl, step: PlanStep) -> StepOutcome:
    """Revalidate right before acting, then remove; `SpaceReclaimed` is kept for the prune."""
    try:
        if step.kind is ActionKind.IMAGE_REMOVE:
            return _run_image_step(control=control, step=step)
        if step.kind is ActionKind.VOLUME_REMOVE:
            return _run_volume_step(control=control, step=step)
        freed = control.prune_build_cache()
        return StepOutcome(order=step.order, status=StepStatus.DONE, freed_bytes=freed)
    except Exception as error:
        return failed_outcome(order=step.order, error=error)


def _is_disk_step(*, plan: Plan, step: PlanStep) -> bool:
    if step.kind in DISK_DOCKER_KINDS | DISK_FS_KINDS:
        return True
    return (
        step.kind is ActionKind.CONTAINER_REMOVE
        and plan.request.kind is ActionKind.CONTAINERS_PRUNE_STOPPED
    )


def log_disk_outcomes(*, plan: Plan, outcomes: Sequence[StepOutcome]) -> None:
    """One INFO line per executed disk step: action, target, outcome, bytes freed (8.4)."""
    steps = {step.order: step for step in plan.steps}
    for outcome in outcomes:
        step = steps.get(outcome.order)
        if step is None or not _is_disk_step(plan=plan, step=step):
            continue
        freed = UNKNOWN_BYTES if outcome.freed_bytes is None else outcome.freed_bytes
        # A folder step logs its path: its label is a translated title (F8).
        fingerprint = step.fingerprint
        target = (
            fingerprint.realpath if isinstance(fingerprint, DirFingerprint) else step.target_label
        )
        LOGGER.info(
            "disk action=%s target=%s outcome=%s freed_bytes=%s",
            step.kind.value,
            target,
            outcome.status.value,
            freed,
        )
