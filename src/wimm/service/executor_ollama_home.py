"""Removal of one model of the user's own ollama store with `ollama rm` (T-6.38c, design L5).

`ollama rm` deletes from the store of whichever server answers, so a home model is removed only
while the user's own server serves the home store (situation S1), read now and not from the plan.
The manifest is checked as a file; after the command it must be gone. No file is ever deleted
by wimm: a manifest that is still there is a failure, not a reason to unlink it.
"""

import logging
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from wimm.collectors.cache_items import TEXT_PREFIXES, list_tree
from wimm.core.cache_catalog import CacheAccess
from wimm.core.cache_items import items_for
from wimm.core.cache_items_ollama import MANIFEST_DEPTH, MANIFEST_DIR, display_name
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S
from wimm.core.ollama_names import is_valid_model_name
from wimm.core.ollama_served import ServedStore
from wimm.i18n import N_
from wimm.model.actions import ItemFingerprint, PlanStep
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind

from .control_protocols import StepOutcome, StepStatus
from .errors import ControlFailed, InvalidRequest, ProtectedTarget, TargetChanged
from .executor_ollama_item import (
    END_OF_OPTIONS,
    REMOVE_COMMAND,
    command_detail,
    list_models,
    ollama_tool,
    run_ollama,
    served_situation,
)
from .fs_controls import DiskFsControl

LOGGER = logging.getLogger(__name__)


class ServerNotRunning(ProtectedTarget):
    """S0: no `ollama serve`, so `ollama rm` has nobody to ask."""

    message = "No ollama server is running, nothing was removed"
    user_message = N_("Avvia ollama per rimuovere un modello")


class ServerUsesOtherStore(ProtectedTarget):
    """S1': the user's server serves another models folder, or its environment is unreadable."""

    message = "The active ollama server uses another models folder, nothing was removed"
    user_message = N_("Il server ollama attivo usa un'altra cartella di modelli")


class ServerIsSystem(ProtectedTarget):
    """S2: the server is another user's: it would delete from the system store."""

    message = "The active ollama server is the system one and does not see these models"
    user_message = N_("Il server ollama attivo è quello di sistema e non vede questi modelli")


class ServersAmbiguous(ProtectedTarget):
    """S3: two servers, or a remote host: which store `ollama rm` reaches is unknown."""

    message = "It is not clear which ollama server answers, nothing was removed"
    user_message = N_("Non è chiaro quale server ollama risponda: non è stato rimosso nulla")


REFUSALS: Mapping[ServedStore, type[ProtectedTarget]] = {
    ServedStore.NONE: ServerNotRunning,
    ServedStore.USER_OTHER: ServerUsesOtherStore,
    ServedStore.SYSTEM: ServerIsSystem,
    ServedStore.AMBIGUOUS: ServersAmbiguous,
}


class HomeModel(NamedTuple):
    """What the check established about the planned manifest."""

    name: str
    size: int


def _no_sleep(seconds: float) -> None:
    """The listing runs inside an action: no pacing."""


def _fingerprint(*, step: PlanStep) -> ItemFingerprint:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ItemFingerprint):
        raise InvalidRequest(f"Step {step.order} has no cache item fingerprint")
    return fingerprint


def _store_root(*, fingerprint: ItemFingerprint, control: DiskFsControl) -> Path | None:
    """The cleanable ollama cache of the start-up table that holds the planned path."""
    for cache in control.caches.caches:
        inside = Path(fingerprint.realpath).is_relative_to(cache.path)
        if cache.kind is CacheKind.OLLAMA and cache.access is CacheAccess.CLEANABLE and inside:
            return cache.path
    return None


def is_home_ollama_step(*, step: PlanStep, control: DiskFsControl) -> bool:
    """True for an item fingerprint that lies in the home ollama store of the table."""
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, ItemFingerprint):
        return False
    return _store_root(fingerprint=fingerprint, control=control) is not None


def _require_home_server(*, control: DiskFsControl) -> None:
    situation = served_situation(control=control)
    if situation is ServedStore.USER_HOME:
        return
    error = REFUSALS[situation]
    raise error(f"{error.message} (situation: {situation.value})")


def _manifest_parts(*, root: Path, fingerprint: ItemFingerprint) -> tuple[str, ...]:
    """`manifests/<host>/<namespace>/<name>/<tag>` below the root, or refuse."""
    parts = Path(fingerprint.realpath).relative_to(root).parts
    if len(parts) != MANIFEST_DEPTH or parts[0] != MANIFEST_DIR:
        raise ProtectedTarget(f"{fingerprint.realpath} is not a model manifest of the store")
    return parts


def _lstat_chain(*, root: Path, parts: tuple[str, ...]) -> os.stat_result | None:
    """lstat the root and every component below it; None if one is missing, raise on a link."""
    info: os.stat_result | None = None
    for depth in range(len(parts) + 1):
        path = root.joinpath(*parts[:depth])
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise TargetChanged(f"{path} is a symlink")
    return info


def _verify_manifest(
    *, root: Path, parts: tuple[str, ...], fingerprint: ItemFingerprint, control: DiskFsControl
) -> bool:
    """True if the planned manifest is still the same regular file; False if it is gone."""
    path = fingerprint.realpath
    info = _lstat_chain(root=root, parts=parts)
    if info is None:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise TargetChanged(f"{path} is no longer a regular file")
    if (info.st_ino, info.st_dev) != (fingerprint.st_ino, fingerprint.st_dev):
        raise TargetChanged(f"{path} is not the same file the plan showed")
    if control.owner_of(path) != control.uid:
        raise ProtectedTarget(f"{path} is not owned by the current user")
    return True


def _recognise(*, root: Path, fingerprint: ItemFingerprint) -> CacheItem:
    """The manifest must be a model for the pure rule as the store is now."""
    prefix = TEXT_PREFIXES[CacheKind.OLLAMA]
    listing = list_tree(root=root, sleep=_no_sleep, text_prefix=prefix)
    items, _ = items_for(CacheKind.OLLAMA, listing, listing.disk_bytes)
    for item in items:
        if item.path == fingerprint.realpath:
            return item
    raise ProtectedTarget(f"{fingerprint.realpath} is no longer recognised as an ollama model")


def _inspect(*, step: PlanStep, control: DiskFsControl) -> HomeModel | None:
    """Every condition of the removal, read now; None if the manifest is already gone."""
    fingerprint = _fingerprint(step=step)
    root = _store_root(fingerprint=fingerprint, control=control)
    if root is None:
        raise ProtectedTarget(f"{fingerprint.realpath} is not in the ollama store of the table")
    _require_home_server(control=control)
    parts = _manifest_parts(root=root, fingerprint=fingerprint)
    name = display_name(parts=list(parts))
    if not is_valid_model_name(name=name):
        raise ProtectedTarget(f"{name} is not a valid ollama model name")
    if not _verify_manifest(root=root, parts=parts, fingerprint=fingerprint, control=control):
        return None
    return HomeModel(name=name, size=_recognise(root=root, fingerprint=fingerprint).size)


def _require_listed_once(*, tool: str, name: str, control: DiskFsControl) -> None:
    """`ollama list` must show exactly one row with this name, or `rm` could hit another model."""
    rows = [model for model in list_models(tool=tool, control=control) if model.name == name]
    if len(rows) != 1:
        raise TargetChanged(f"{name} is listed {len(rows)} times by ollama list, expected once")


def check_ollama_home_item(*, step: PlanStep, control: DiskFsControl) -> bool:
    """Raise if the model must not be removed now; True if its manifest is there, False if gone."""
    ollama_tool(control=control)
    return _inspect(step=step, control=control) is not None


def run_ollama_home_item(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    """Check again, `ollama rm`, then look for the manifest: DONE only if it is gone.

    `freed_bytes` is the size of the blobs only this model owns, as the pure rule counts them
    at execution time: the plan's reclaim is not carried by the step.
    """
    tool = ollama_tool(control=control)
    model = _inspect(step=step, control=control)
    if model is None:
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    _require_listed_once(tool=tool, name=model.name, control=control)
    argv = [tool, REMOVE_COMMAND, END_OF_OPTIONS, model.name]
    result = run_ollama(control=control, argv=argv, timeout_s=CACHE_COMMAND_TIMEOUT_S)
    if result.returncode:
        detail = command_detail(result=result)
        raise ControlFailed(f"ollama rm exited with code {result.returncode}: {detail}")
    if os.path.lexists(_fingerprint(step=step).realpath):
        raise ControlFailed(f"The manifest of {model.name} is still there after ollama rm")
    LOGGER.info("Removed the ollama model %s", model.name)
    return StepOutcome(order=step.order, status=StepStatus.DONE, freed_bytes=model.size)
