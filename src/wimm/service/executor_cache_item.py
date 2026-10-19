"""Removal of one cache item, a HuggingFace model folder and its exclusive blobs (S10-S13).

Everything is decided at execution time from the table resolved at start and from a fresh
listing of the cache; the plan only says which folder and which blobs the user saw.
"""

import os
import stat
from pathlib import Path

from wimm.collectors.cache_items import list_tree
from wimm.core.cache_catalog import CacheAccess
from wimm.core.cache_items import TreeListing, items_for
from wimm.i18n import N_
from wimm.model.actions import DirFingerprint, ItemFingerprint, PlanStep
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind

from .control_protocols import StepOutcome, StepStatus
from .errors import ControlFailed, InvalidRequest, ProtectedTarget, TargetChanged
from .fs_controls import DiskFsControl
from .safe_tree import TreeRemoval, remove_directory, remove_file

LOCKS_DIR = ".locks"
# A lock touched this recently means a download is still writing the model (S13).
LOCK_QUIET_S = 600


class DownloadInProgress(ProtectedTarget):
    """The hub client touched the model's lock files a few minutes ago."""

    message = "A lock of this model changed less than 10 minutes ago, a download may be running"
    user_message = N_("Un download sta scrivendo questo modello: riprova tra qualche minuto")


def _fingerprint(*, step: PlanStep) -> ItemFingerprint:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ItemFingerprint):
        raise InvalidRequest(f"Step {step.order} has no cache item fingerprint")
    return fingerprint


def _hub_of(*, folder: str, control: DiskFsControl) -> Path:
    """The cleanable HuggingFace cache that directly holds the folder, by the start-up table."""
    parent = str(Path(folder).parent)
    for cache in control.caches.caches:
        is_hub = cache.kind is CacheKind.HUGGINGFACE and cache.access is CacheAccess.CLEANABLE
        if is_hub and str(cache.path) == parent:
            return cache.path
    raise ProtectedTarget(f"{folder} is not directly inside a HuggingFace cache of the table")


def _verify_folder(*, fingerprint: ItemFingerprint) -> bool:
    """True if the planned folder is still there; False if gone; raise if it is not the same."""
    path = fingerprint.realpath
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        raise TargetChanged(f"{path} is no longer a real directory")
    if (info.st_ino, info.st_dev) != (fingerprint.st_ino, fingerprint.st_dev):
        raise TargetChanged(f"{path} is not the same folder the plan showed")
    if os.path.realpath(path) != path:
        raise TargetChanged(f"{path} is reached through a symlink")
    return True


def _no_sleep(seconds: float) -> None:
    """The listing runs inside an action: no pacing."""


def _fresh_item(*, hub: Path, fingerprint: ItemFingerprint) -> tuple[CacheItem, TreeListing]:
    """The item as the pure rule sees the cache now; the folder must still be one."""
    listing = list_tree(root=hub, sleep=_no_sleep)
    items, _ = items_for(CacheKind.HUGGINGFACE, listing, listing.disk_bytes)
    for item in items:
        if item.path == fingerprint.realpath and item.id == Path(item.path).name:
            return item, listing
    raise ProtectedTarget(f"{fingerprint.realpath} is no longer recognised as a cached model")


def _refuse_fresh_lock(*, hub: Path, name: str, control: DiskFsControl) -> None:
    def unreadable(error: OSError) -> None:
        if not isinstance(error, FileNotFoundError):
            raise ProtectedTarget(f"The locks of {name} could not be read") from error

    now = control.clock()
    for current, _, files in os.walk(hub / LOCKS_DIR / name, onerror=unreadable):
        for file in files:
            if now - os.lstat(Path(current) / file).st_mtime < LOCK_QUIET_S:
                raise DownloadInProgress()


def check_cache_item(*, step: PlanStep, control: DiskFsControl) -> bool:
    """Raise if the item must not be removed now; True if its folder is there, False if gone."""
    fingerprint = _fingerprint(step=step)
    hub = _hub_of(folder=fingerprint.realpath, control=control)
    if not _verify_folder(fingerprint=fingerprint):
        return False
    if control.owner_of(fingerprint.realpath) != control.uid:
        raise ProtectedTarget(f"{fingerprint.realpath} is not owned by the current user")
    if fingerprint.realpath in control.mounts():
        raise TargetChanged(f"{fingerprint.realpath} is a mount point, nothing was touched")
    _fresh_item(hub=hub, fingerprint=fingerprint)
    _refuse_fresh_lock(hub=hub, name=Path(fingerprint.realpath).name, control=control)
    return True


def _remove_blobs(
    *, hub: Path, fingerprint: ItemFingerprint, item: CacheItem, listing: TreeListing
) -> tuple[TreeRemoval, int]:
    """Remove the planned blobs that are still exclusive and unchanged; count those kept."""
    exclusive = {(b.path, b.st_dev, b.st_ino) for b in item.blobs}
    present = {entry.path for entry in listing.entries}
    removal, kept = TreeRemoval(), 0
    for blob in fingerprint.blobs:
        if (blob.path, blob.st_dev, blob.st_ino) not in exclusive:
            kept += blob.path in present
            continue
        try:
            removal += remove_file(
                root=str(hub), relative=blob.path, st_ino=blob.st_ino, st_dev=blob.st_dev
            )
        except FileNotFoundError:
            continue
        except TargetChanged:
            kept += 1
        except OSError as error:
            sample = (f"{blob.path}: {error.strerror or error}",)
            removal += TreeRemoval(error_count=1, error_samples=sample)
    return removal, kept


def _require_complete(*, removal: TreeRemoval, where: str) -> None:
    if removal.remaining:
        raise ControlFailed(
            f"{removal.remaining} entries left in {where} "
            f"(first: {', '.join(removal.error_samples[:1]) or 'mount point skipped'})"
        )


def run_cache_item(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    """Remove the folder, then the blobs that the fresh listing still shows as exclusive."""
    fingerprint = _fingerprint(step=step)
    hub = _hub_of(folder=fingerprint.realpath, control=control)
    item, listing = _fresh_item(hub=hub, fingerprint=fingerprint)
    folder = DirFingerprint(
        realpath=fingerprint.realpath, st_ino=fingerprint.st_ino, st_dev=fingerprint.st_dev
    )
    removal = remove_directory(fingerprint=folder, mountpoints=control.mounts())
    _require_complete(removal=removal, where=fingerprint.realpath)
    blobs, kept = _remove_blobs(hub=hub, fingerprint=fingerprint, item=item, listing=listing)
    removal += blobs
    _require_complete(removal=removal, where=str(hub))
    return StepOutcome(
        order=step.order,
        status=StepStatus.DONE,
        # A technical note like the other step messages; the UI builds its texts from the status.
        message=f"{kept} store file(s) kept: no longer used only by this model" if kept else None,
        freed_bytes=removal.freed_bytes,
    )
