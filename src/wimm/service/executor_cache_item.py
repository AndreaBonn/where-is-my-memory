"""Removal of one cache item, a HuggingFace model folder and its exclusive blobs (S10-S13).

Everything is decided at execution time from the table resolved at start and from a fresh
listing of the cache; the plan only says which folder and which blobs the user saw (paths and
identities, nothing else is trusted).
"""

import os
import stat
from pathlib import Path

from wimm.collectors.cache_items import list_tree
from wimm.core.cache_catalog import CacheAccess
from wimm.core.cache_items import TreeListing, items_for
from wimm.core.cache_items_hf import STORE_PREFIX, reached_identities
from wimm.i18n import N_
from wimm.model.actions import DirFingerprint, ItemFingerprint, PlanStep
from wimm.model.cache_items import ItemBlob
from wimm.model.disk import CacheKind

from .control_protocols import StepOutcome, StepStatus
from .errors import InvalidRequest, ProtectedTarget, TargetChanged
from .fs_controls import DiskFsControl
from .safe_file import remove_file
from .safe_tree import TreeRemoval, remove_directory

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


def _recognise_item(*, hub: Path, fingerprint: ItemFingerprint) -> None:
    """The folder must be a cached model for the pure rule as the cache is now."""
    listing = list_tree(root=hub, sleep=_no_sleep)
    items, _ = items_for(CacheKind.HUGGINGFACE, listing, listing.disk_bytes)
    if not any(i.path == fingerprint.realpath and i.id == Path(i.path).name for i in items):
        raise ProtectedTarget(f"{fingerprint.realpath} is no longer recognised as a cached model")


def _lock_age_ok(*, path: Path, now: float) -> bool:
    """False if the lock was touched recently; a lock that vanished meanwhile counts as old."""
    try:
        return now - os.lstat(path).st_mtime >= LOCK_QUIET_S
    except FileNotFoundError:
        return True


def _refuse_fresh_lock(*, hub: Path, name: str, control: DiskFsControl) -> None:
    def unreadable(error: OSError) -> None:
        if not isinstance(error, FileNotFoundError):
            raise ProtectedTarget(f"The locks of {name} could not be read") from error

    now = control.clock()
    for current, _, files in os.walk(hub / LOCKS_DIR / name, onerror=unreadable):
        if not all(_lock_age_ok(path=Path(current) / file, now=now) for file in files):
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
    _recognise_item(hub=hub, fingerprint=fingerprint)
    _refuse_fresh_lock(hub=hub, name=Path(fingerprint.realpath).name, control=control)
    return True


def _remove_one(*, hub: Path, blob: ItemBlob) -> tuple[TreeRemoval, bool]:
    """Unlink one planned blob; (what was removed, True if it had to be kept)."""
    try:
        return remove_file(
            root=str(hub), relative=blob.path, st_ino=blob.st_ino, st_dev=blob.st_dev
        ), False
    except FileNotFoundError:
        return TreeRemoval(), False
    except TargetChanged:
        return TreeRemoval(), True
    except OSError as error:
        sample = (f"{blob.path}: {error.strerror or error}",)
        return TreeRemoval(error_count=1, error_samples=sample), False


def _remove_blobs(
    *, hub: Path, fingerprint: ItemFingerprint, listing: TreeListing
) -> tuple[TreeRemoval, int]:
    """Remove the planned blobs that no remaining repo reaches; count those kept.

    `listing` is taken after the folder is gone, so a link another repo gained meanwhile shows.
    A walk that skipped anything may have missed such a link: then every planned blob is kept.
    """
    if listing.skipped:
        return TreeRemoval(), len(fingerprint.blobs)
    reached = reached_identities(listing=listing)
    by_path = {entry.path: entry for entry in listing.entries}
    removal, kept = TreeRemoval(), 0
    for blob in fingerprint.blobs:
        entry = by_path.get(blob.path)
        if entry is None:
            continue
        identity = (blob.st_dev, blob.st_ino)
        if (
            (entry.st_dev, entry.st_ino) != identity
            or identity in reached
            or not blob.path.startswith(STORE_PREFIX)
        ):
            kept += 1
        else:
            done, was_kept = _remove_one(hub=hub, blob=blob)
            removal += done
            kept += was_kept
    return removal, kept


def _left_behind(*, order: int, removal: TreeRemoval, where: str) -> StepOutcome:
    """The folder could not be emptied: fail, but report the bytes already freed."""
    first = ", ".join(removal.error_samples[:1]) or "mount point skipped"
    message = f"{removal.remaining} entries left in {where} (first: {first})"
    return StepOutcome(
        order=order, status=StepStatus.FAILED, message=message, freed_bytes=removal.freed_bytes
    )


def _kept_note(*, kept: int, skipped: int) -> str | None:
    if not kept:
        return None
    if skipped:
        return (
            f"{kept} store file(s) kept: "
            f"{skipped} cache entries could not be read after the removal"
        )
    return f"{kept} store file(s) kept: no longer used only by this model"


def _outcome(
    *, order: int, removal: TreeRemoval, blobs: TreeRemoval, note: str | None
) -> StepOutcome:
    if blobs.error_count:
        # The folder is gone: report what was freed instead of hiding it behind the failure.
        message = (
            f"{blobs.error_count} store file(s) could not be removed "
            f"(first: {blobs.error_samples[0]})"
        )
        return StepOutcome(
            order=order, status=StepStatus.FAILED, message=message, freed_bytes=removal.freed_bytes
        )
    # `note` is technical like the other step messages; the UI builds its texts from the status.
    return StepOutcome(
        order=order, status=StepStatus.DONE, message=note, freed_bytes=removal.freed_bytes
    )


def run_cache_item(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    """Remove the folder, then the planned blobs that a fresh listing shows nobody reaches."""
    fingerprint = _fingerprint(step=step)
    hub = _hub_of(folder=fingerprint.realpath, control=control)
    folder = DirFingerprint(
        realpath=fingerprint.realpath, st_ino=fingerprint.st_ino, st_dev=fingerprint.st_dev
    )
    removal = remove_directory(fingerprint=folder, mountpoints=control.mounts())
    if removal.remaining:
        return _left_behind(order=step.order, removal=removal, where=fingerprint.realpath)
    listing = list_tree(root=hub, sleep=_no_sleep)
    blobs, kept = _remove_blobs(hub=hub, fingerprint=fingerprint, listing=listing)
    note = _kept_note(kept=kept, skipped=listing.skipped)
    return _outcome(order=step.order, removal=removal + blobs, blobs=blobs, note=note)
