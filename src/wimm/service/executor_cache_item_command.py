"""Android item commands: tool-only removal and live emulator protection (S12-S13)."""

import os
from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from wimm.core.cache_catalog import CacheAccess
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S
from wimm.model.actions import PlanStep
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind, DiskReport

from .control_protocols import StepOutcome, StepStatus
from .errors import ControlFailed, ProtectedTarget
from .fs_controls import DiskFsControl

ANDROID_TOOLS = {CacheKind.ANDROID_SDK: "sdkmanager", CacheKind.ANDROID_AVD: "avdmanager"}
SDK_TOOLS = Path("cmdline-tools/latest/bin")
AVD_OPTION = "-avd"
AVD_SUFFIX = ".avd"
EMULATOR_PREFIXES = ("emulator", "qemu-system-")
AVD_INI_SUFFIX = ".ini"
INI_PATH_KEY = "path="
# An AVD .ini is a few lines; anything larger is not one and is not parsed.
MAX_INI_BYTES = 64 * 1024


def resolve_item_tool(*, kind: CacheKind, control: DiskFsControl) -> str:
    """Prefer the SDK of the start-up table, then the injected PATH lookup."""
    name = ANDROID_TOOLS[kind]
    for cache in control.caches.caches:
        if cache.kind is CacheKind.ANDROID_SDK and cache.access is CacheAccess.CLEANABLE:
            candidate = cache.path / SDK_TOOLS / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    tool = control.which(name)
    if tool is None or not os.path.isabs(tool):
        raise ProtectedTarget(f"The {name} tool is not available by an absolute path")
    return tool


def planning_report(
    *, report: DiskReport | None, control: DiskFsControl | None
) -> DiskReport | None:
    """Withhold Android items whose command is absent before building a confirmation plan."""
    if report is None:
        return None
    missing = set(ANDROID_TOOLS)
    if control is not None:
        for kind in ANDROID_TOOLS:
            try:
                resolve_item_tool(kind=kind, control=control)
            except ProtectedTarget:
                continue
            missing.discard(kind)
    caches = tuple(replace(c, items=()) if c.kind in missing else c for c in report.caches)
    return replace(report, caches=caches)


def item_argv(
    *, kind: CacheKind, root: Path, folder: Path, control: DiskFsControl
) -> tuple[str, ...]:
    """Construct arguments only after the caller has recognised the live item."""
    tool = resolve_item_tool(kind=kind, control=control)
    if kind is CacheKind.ANDROID_SDK:
        package_id = ";".join(folder.relative_to(root).parts)
        return tool, f"--sdk_root={root}", "--uninstall", package_id
    name = folder.name.removesuffix(AVD_SUFFIX)
    _refuse_running_emulator(name=name, control=control)
    _require_ini_pointing_to(folder=folder, name=name)
    return tool, "delete", "avd", "-n", name


def _names_avd(*, argv: Sequence[str], name: str) -> bool:
    """`-avd <name>`, `-avd=<name>` and `@<name>` all start the emulator on that AVD."""
    if f"{AVD_OPTION}={name}" in argv or f"@{name}" in argv:
        return True
    return any(arg == AVD_OPTION and following == name for arg, following in pairwise(argv))


def _refuse_running_emulator(*, name: str, control: DiskFsControl) -> None:
    for process_name, argv in control.processes():
        names = (process_name, Path(argv[0]).name if argv else "")
        is_emulator = any(each.startswith(EMULATOR_PREFIXES) for each in names)
        if is_emulator and _names_avd(argv=argv, name=name):
            raise ProtectedTarget(f"The emulator for {name} is running")


def _read_ini(*, path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        return handle.read(MAX_INI_BYTES + 1).decode("utf-8", errors="replace")


def _require_ini_pointing_to(*, folder: Path, name: str) -> None:
    """avdmanager deletes the folder the .ini names: it must be the checked one, exactly."""
    ini = folder.parent / f"{name}{AVD_INI_SUFFIX}"
    try:
        text = _read_ini(path=ini)
    except OSError as err:
        raise ProtectedTarget(f"{ini} cannot be read, the tool target is unknown") from err
    lines = text.splitlines()
    paths = [line[len(INI_PATH_KEY) :].strip() for line in lines if line.startswith(INI_PATH_KEY)]
    if len(text) > MAX_INI_BYTES or paths != [str(folder)]:
        raise ProtectedTarget(f"{ini} does not point to {folder}")


def run_item_command(
    *, step: PlanStep, control: DiskFsControl, argv: tuple[str, ...], item: CacheItem
) -> StepOutcome:
    """A successful tool must remove the folder; never fall back to filesystem deletion."""
    env = {key: os.environ[key] for key in ("PATH", "LANG", "JAVA_HOME") if key in os.environ}
    env["HOME"] = str(control.home)
    if Path(argv[0]).name == ANDROID_TOOLS[CacheKind.ANDROID_AVD]:
        env["ANDROID_AVD_HOME"] = str(Path(item.path).parent)
    result = control.runner.run(argv=argv, timeout_s=CACHE_COMMAND_TIMEOUT_S, env=env)
    if result.returncode:
        raise ControlFailed(f"{argv[0]} exited with code {result.returncode}: {result.output}")
    try:
        os.lstat(item.path)
    except FileNotFoundError:
        remaining = sum(
            blob.size for blob in item.blobs if os.path.lexists(Path(item.path).parent / blob.path)
        )
        return StepOutcome(
            order=step.order, status=StepStatus.DONE, freed_bytes=item.size - remaining
        )
    raise ControlFailed(f"The tool left {item.path} in place")
