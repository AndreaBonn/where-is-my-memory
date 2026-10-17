"""Folder, cache and trash steps (SPECIFICHE 8.2, 8.4): revalidate, then remove safely."""

import os
import stat
from pathlib import Path

from wimm.collectors.devdir_context import read_devdir_context
from wimm.collectors.devdirs import project_age_days
from wimm.core.constants import (
    CACHE_COMMAND_TIMEOUT_S,
    CACHE_ENV_VARS,
    CACHE_RELATIVE_PATHS,
    TRASH_CONTENT_DIRS,
)
from wimm.core.devdir_rules import MARKERS_BY_NAME, classify_devdir
from wimm.model.actions import DirFingerprint, PlanStep
from wimm.model.enums import ActionKind

from .control_protocols import StepOutcome, StepStatus, failed_outcome
from .errors import ControlFailed, InvalidRequest, ProtectedTarget, TargetChanged
from .fs_controls import DiskFsControl
from .safe_tree import TreeRemoval, empty_directory, remove_directory

DISK_FS_KINDS = frozenset(
    {ActionKind.CACHE_CLEAN, ActionKind.TRASH_EMPTY, ActionKind.DEVDIR_DELETE}
)
PIP_KIND = "pip"
TRASH_KIND = "trash"


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
    """Under a configured root whose real path is itself inside the real home."""
    home = Path(os.path.realpath(control.home))
    for root in control.roots:
        real = Path(os.path.realpath(root))
        if real.is_relative_to(home) and path.is_relative_to(real):
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


def _cache_kind(*, fingerprint: DirFingerprint, control: DiskFsControl) -> str:
    """The cache this folder is, by its place under the executor's home, never by the plan."""
    home = Path(os.path.realpath(control.home))
    for value, relative in CACHE_RELATIVE_PATHS:
        if fingerprint.realpath == str(home / relative):
            return value
    raise ProtectedTarget(f"{fingerprint.realpath} is not a cache folder under the home")


def _check_cache(*, step: PlanStep, control: DiskFsControl) -> bool:
    fingerprint = _fingerprint(step=step)
    kind = _cache_kind(fingerprint=fingerprint, control=control)
    if (kind == TRASH_KIND) != (step.kind is ActionKind.TRASH_EMPTY):
        raise ProtectedTarget(f"{fingerprint.realpath} does not match {step.kind.value}")
    return _verify_directory(fingerprint=fingerprint)


def check_disk_fs(*, step: PlanStep, control: DiskFsControl) -> bool:
    """Raise if the step must not run now; True if its folder is there, False if gone."""
    if step.kind is ActionKind.DEVDIR_DELETE:
        return _check_devdir(fingerprint=_fingerprint(step=step), control=control)
    return _check_cache(step=step, control=control)


def _tree_outcome(*, step: PlanStep, removal: TreeRemoval, done: bool) -> StepOutcome:
    """DONE when the target is as planned, FAILED with a count when entries remain."""
    if removal.remaining:
        first = removal.error_samples[0] if removal.error_samples else "mount point skipped"
        message = f"{removal.remaining} entries left in {step.target_label} (first: {first})"
        return StepOutcome(order=step.order, status=StepStatus.FAILED, message=message)
    status = StepStatus.DONE if done or removal.removed else StepStatus.ALREADY_GONE
    return StepOutcome(order=step.order, status=status, freed_bytes=removal.freed_bytes)


def _cache_argv(*, kind: str, folder: str) -> tuple[str, ...] | None:
    """The cleaning command aimed at the planned folder, not at what the environment says.

    uv: `uv cache prune --cache-dir <dir>`; pip: `pip --cache-dir <dir> cache purge`; npm: the
    `--cache` option is the parent of `_cacache`, where npm keeps it.
    """
    if kind == "uv":
        return ("uv", "cache", "prune", "--cache-dir", folder)
    if kind == PIP_KIND:
        return ("pip", "--cache-dir", folder, "cache", "purge")
    if kind == "npm":
        return ("npm", "cache", "clean", "--force", "--cache", str(Path(folder).parent))
    return None


def _cache_env() -> dict[str, str]:
    """The inherited environment without the variables that redirect a cache tool."""
    hidden = {name.lower() for name in CACHE_ENV_VARS}
    return {name: value for name, value in os.environ.items() if name.lower() not in hidden}


def _run_command(*, step: PlanStep, control: DiskFsControl, argv: tuple[str, ...]) -> StepOutcome:
    result = control.runner.run(argv=argv, timeout_s=CACHE_COMMAND_TIMEOUT_S, env=_cache_env())
    if result.returncode != 0:
        raise ControlFailed(f"{argv[0]} exited with code {result.returncode}: {result.output}")
    return StepOutcome(order=step.order, status=StepStatus.DONE)


def _run_cache(*, step: PlanStep, control: DiskFsControl) -> StepOutcome:
    fingerprint = _fingerprint(step=step)
    kind = _cache_kind(fingerprint=fingerprint, control=control)
    argv = _cache_argv(kind=kind, folder=fingerprint.realpath)
    if argv is not None and (kind != PIP_KIND or control.which(PIP_KIND) is not None):
        return _run_command(step=step, control=control, argv=argv)
    removal = empty_directory(fingerprint=fingerprint, mountpoints=control.mounts())
    return _tree_outcome(step=step, removal=removal, done=False)


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
