"""Folder, cache and trash steps (SPECIFICHE 8.2, 8.4): revalidate, then remove safely."""

import logging
import os
import stat
from pathlib import Path

from wimm.collectors.devdir_context import read_devdir_context
from wimm.collectors.devdirs import project_age_days
from wimm.core.cache_catalog import (
    CLEAN_SUBDIRS,
    COMMAND_ONLY_KINDS,
    CacheAccess,
    command_argv,
    command_env,
    withheld_kinds,
)
from wimm.core.cache_specs import CACHE_COMMANDS
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S, TRASH_CONTENT_DIRS
from wimm.core.devdir_rules import MARKERS_BY_NAME, classify_devdir
from wimm.core.ollama_serve import is_ollama_serve
from wimm.core.root_policy import root_refusal
from wimm.i18n import N_
from wimm.model.actions import DirFingerprint, PlanStep
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind

from .control_protocols import StepOutcome, StepStatus, failed_outcome
from .errors import CacheIsLink, ControlFailed, InvalidRequest, ProtectedTarget, TargetChanged
from .fs_controls import DiskFsControl
from .safe_tree import TreeRemoval, empty_directory, remove_directory

LOGGER = logging.getLogger(__name__)
DISK_FS_KINDS = frozenset(
    {ActionKind.CACHE_CLEAN, ActionKind.TRASH_EMPTY, ActionKind.DEVDIR_DELETE}
)


class OllamaServing(ProtectedTarget):
    """The ollama server is alive: it holds the models open (R24)."""

    message = "ollama serve is running, the models are not cleaned"
    user_message = N_("Chiudi ollama (ollama serve) prima di cancellare i modelli")


def _refuse_while_ollama_serves(*, control: DiskFsControl) -> None:
    for name, argv in control.processes():
        if is_ollama_serve(name=name, argv=argv):
            raise OllamaServing()


def _fingerprint(*, step: PlanStep) -> DirFingerprint:
    fingerprint = step.fingerprint
    if not isinstance(fingerprint, DirFingerprint):
        raise InvalidRequest(f"Step {step.order} has no folder fingerprint")
    return fingerprint


def _verify_directory(*, fingerprint: DirFingerprint) -> bool:
    """True if the planned folder is still there; False if gone; raise if it is not the same.

    A symlink, a replaced inode or a path that crosses a symlink is `TargetChanged`.
    """
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


def _inside_a_root(*, path: Path, control: DiskFsControl) -> bool:
    """Under a configured root that ADR-007 admits when observed now.

    The root is read again at execution time (owner, ancestors, mount); facts that cannot be
    read count as a refusal. A different disk mounted at the planned path is caught by the
    folder fingerprint (`st_dev`), so the plan does not record the root's device.
    """
    home = Path(os.path.realpath(control.home))
    for root in control.roots:
        if not path.is_relative_to(os.path.realpath(root)):
            continue
        facts = control.read_facts(path=root)
        if facts is None or not path.is_relative_to(facts.realpath):
            continue
        if root_refusal(facts=facts, home=home) is None:
            return True
    return False


def _require_devdir_markers(*, path: Path, control: DiskFsControl) -> None:
    """Classify the folder by what sits around it now, not by what the plan saw.

    The marker (`Cargo.toml`, `pyvenv.cfg`...) or the second signal may be gone since the plan.
    """
    try:
        context = read_devdir_context(path=path, home=control.home)
    except OSError as error:
        raise ProtectedTarget(f"{path.parent} could not be read to check {path.name}") from error
    if not classify_devdir(name=path.name, context=context):
        raise ProtectedTarget(f"{path} is no longer recognised as a rebuildable folder")


def _check_devdir(*, fingerprint: DirFingerprint, control: DiskFsControl) -> bool:
    path = Path(fingerprint.realpath)
    if path.name not in MARKERS_BY_NAME:
        raise ProtectedTarget(f"{path.name} is not a dependency folder name")
    if not _inside_a_root(path=path, control=control):
        raise ProtectedTarget(f"{path} is not inside a configured development root")
    if not _verify_directory(fingerprint=fingerprint):
        return False
    _require_devdir_markers(path=path, control=control)
    age = project_age_days(project=path.parent, now=control.clock())
    if age is None:
        raise TargetChanged(f"{path.parent} could not be read to check its age")
    if age < control.min_age_days:
        raise TargetChanged(f"{path.parent} was touched {age} days ago, newer than the plan allows")
    if any(cwd.is_relative_to(path.parent) for cwd in control.cwds.cwds()):
        raise ProtectedTarget(f"A process has its working directory inside {path.parent}")
    return True


def _cache_kind(*, fingerprint: DirFingerprint, control: DiskFsControl) -> CacheKind:
    """The cache this folder is, by its place in the table resolved at start, never by the plan.

    Only a folder the table lists as `CLEANABLE` counts; a folder whose files only the tool's
    own command can remove is refused while that tool is not on PATH.
    """
    for cache in control.caches.caches:
        if cache.access is CacheAccess.CLEANABLE and fingerprint.realpath == str(cache.path):
            if cache.kind in withheld_kinds(which=control.which):
                raise ProtectedTarget(f"{cache.kind.value} can only be cleaned by its own command")
            return cache.kind
    raise ProtectedTarget(f"{fingerprint.realpath} is not a cache folder of the table")


def _check_cache(*, step: PlanStep, control: DiskFsControl) -> bool:
    fingerprint = _fingerprint(step=step)
    kind = _cache_kind(fingerprint=fingerprint, control=control)
    if kind is CacheKind.OLLAMA:
        _refuse_while_ollama_serves(control=control)
    if (kind is CacheKind.TRASH) != (step.kind is ActionKind.TRASH_EMPTY):
        raise ProtectedTarget(f"{fingerprint.realpath} does not match {step.kind.value}")
    if os.path.islink(fingerprint.realpath):
        raise CacheIsLink(f"{fingerprint.realpath} is a symlink, it is not followed")
    if not _verify_directory(fingerprint=fingerprint):
        return False
    if control.owner_of(fingerprint.realpath) != control.uid:
        raise ProtectedTarget(f"{fingerprint.realpath} is not owned by the current user")
    return True


def check_disk_fs(*, step: PlanStep, control: DiskFsControl) -> bool:
    """Raise if the step must not run now; True if its folder is there, False if gone."""
    if step.kind is ActionKind.DEVDIR_DELETE:
        return _check_devdir(fingerprint=_fingerprint(step=step), control=control)
    return _check_cache(step=step, control=control)


def _tree_outcome(*, step: PlanStep, removal: TreeRemoval, done: bool) -> StepOutcome:
    """DONE when the target is as planned, FAILED with a count when entries remain."""
    if removal.remaining:
        first = removal.error_samples[0] if removal.error_samples else "mount point skipped"
        # The folder, not the label: a cache step is labelled with its title (F8).
        where = _fingerprint(step=step).realpath
        message = f"{removal.remaining} entries left in {where} (first: {first})"
        return StepOutcome(order=step.order, status=StepStatus.FAILED, message=message)
    status = StepStatus.DONE if done or removal.removed else StepStatus.ALREADY_GONE
    return StepOutcome(order=step.order, status=status, freed_bytes=removal.freed_bytes)


def _refuse_mount(*, fingerprint: DirFingerprint, control: DiskFsControl) -> None:
    """A native command must not run on a mount point either (`empty_directory` refuses it)."""
    if fingerprint.realpath in control.mounts():
        raise TargetChanged(f"{fingerprint.realpath} is a mount point, nothing was touched")


def _tool_path(*, kind: CacheKind, control: DiskFsControl, command_name: str) -> str | None:
    """The absolute path of the tool, None when it is missing and emptying is allowed."""
    tool = control.which(command_name)
    if tool is None:
        if kind in COMMAND_ONLY_KINDS:
            raise ProtectedTarget(f"{kind.value} can only be cleaned by its own command")
        return None
    if not os.path.isabs(tool):
        raise ProtectedTarget(f"{command_name} resolved to a relative path: {tool}")
    return tool


def _run_command(
    *, step: PlanStep, control: DiskFsControl, argv: tuple[str, ...], env: dict[str, str]
) -> StepOutcome | None:
    """DONE if the command succeeded; None for a yarn that failed (see `_run_cache`)."""
    result = control.runner.run(argv=argv, timeout_s=CACHE_COMMAND_TIMEOUT_S, env=env)
    if result.returncode == 0:
        return StepOutcome(order=step.order, status=StepStatus.DONE)
    if argv[1:3] == ("cache", "clean") and Path(argv[0]).name == "yarn":
        # Yarn Berry has no cache to clean from the neutral directory the command runs in.
        LOGGER.warning("yarn exited with code %s, the folder is emptied instead", result.returncode)
        return None
    raise ControlFailed(f"{argv[0]} exited with code {result.returncode}: {result.output}")


def _empty_cache(*, step: PlanStep, control: DiskFsControl, kind: CacheKind) -> StepOutcome:
    removal = empty_directory(
        fingerprint=_fingerprint(step=step),
        subdirs=CLEAN_SUBDIRS.get(kind, ()),
        mountpoints=control.mounts(),
    )
    return _tree_outcome(step=step, removal=removal, done=False)


def _run_cache(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    """The tool's own command aimed at the planned folder, or emptying when the tool is missing.

    The tool is resolved once and run by its absolute path, with an allowlisted environment.
    """
    fingerprint = _fingerprint(step=step)
    kind = _cache_kind(fingerprint=fingerprint, control=control)
    command = CACHE_COMMANDS.get(kind)
    tool = (
        None
        if command is None
        else _tool_path(kind=kind, control=control, command_name=command.argv[0])
    )
    if command is None or tool is None:
        return _empty_cache(step=step, control=control, kind=kind)
    _refuse_mount(fingerprint=fingerprint, control=control)
    folder = fingerprint.realpath
    argv = command_argv(command=command, tool=tool, folder=folder)
    env = command_env(command=command, folder=folder, environ=os.environ)
    return _run_command(step=step, control=control, argv=argv, env=env) or _empty_cache(
        step=step, control=control, kind=kind
    )


def _run_removal(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    fingerprint = _fingerprint(step=step)
    mounts = control.mounts()
    if step.kind is ActionKind.DEVDIR_DELETE:
        removal = remove_directory(fingerprint=fingerprint, mountpoints=mounts)
        return _tree_outcome(step=step, removal=removal, done=removal.root_removed)
    if step.kind is ActionKind.TRASH_EMPTY:
        removal = empty_directory(
            fingerprint=fingerprint, subdirs=TRASH_CONTENT_DIRS, mountpoints=mounts
        )
        return _tree_outcome(step=step, removal=removal, done=False)
    return _run_cache(step=step, control=control)


def run_disk_fs_step(*, control: DiskFsControl, step: PlanStep) -> StepOutcome:
    """Revalidate right before acting, then remove; a folder that vanished is `already_gone`."""
    try:
        if not check_disk_fs(step=step, control=control):
            return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
        return _run_removal(step=step, control=control)
    except FileNotFoundError:
        return StepOutcome(order=step.order, status=StepStatus.ALREADY_GONE)
    except Exception as error:
        return failed_outcome(order=step.order, error=error)
