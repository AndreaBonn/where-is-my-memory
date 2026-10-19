"""Android item commands: tool-only removal and live emulator protection (S12-S13)."""

import os
from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

from wimm.core.cache_catalog import CacheAccess
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S
from wimm.core.item_tools import ITEM_TOOLS, item_tool, withheld_item_kinds
from wimm.model.actions import PlanStep
from wimm.model.cache_items import CacheItem
from wimm.model.disk import CacheKind, DiskReport

from .control_protocols import StepOutcome, StepStatus
from .errors import ControlFailed, ProtectedTarget
from .fs_controls import DiskFsControl

AVD_OPTION = "-avd"
AVD_SUFFIX = ".avd"
EMULATOR_PREFIXES = ("emulator", "qemu-system-")
AVD_INI_SUFFIX = ".ini"
# The keys avdmanager writes; any other line could be read by it as a different target.
INI_KEYS = frozenset({"avd.ini.encoding", "path", "path.rel", "target"})
INI_SEPARATOR = "="
INI_PATH_KEY = "path"
INI_RELATIVE_KEY = "path.rel"
# An AVD .ini is a few lines; anything larger is not one and is not parsed.
MAX_INI_BYTES = 64 * 1024


def _sdk_roots(*, control: DiskFsControl) -> tuple[str, ...]:
    return tuple(
        str(cache.path)
        for cache in control.caches.caches
        if cache.kind is CacheKind.ANDROID_SDK and cache.access is CacheAccess.CLEANABLE
    )


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_item_tool(*, kind: CacheKind, control: DiskFsControl) -> str:
    """Prefer the SDK of the start-up table, then the injected PATH lookup."""
    tool = item_tool(
        kind=kind,
        sdk_roots=_sdk_roots(control=control),
        is_executable=_is_executable,
        which=control.which,
    )
    if tool is None:
        raise ProtectedTarget(f"The {ITEM_TOOLS[kind]} tool is not available by an absolute path")
    return tool


def planning_report(
    *, report: DiskReport | None, control: DiskFsControl | None
) -> DiskReport | None:
    """Withhold Android items whose command is absent before building a confirmation plan."""
    if report is None:
        return None
    missing = (
        frozenset(ITEM_TOOLS)
        if control is None
        else withheld_item_kinds(
            sdk_roots=_sdk_roots(control=control),
            is_executable=_is_executable,
            which=control.which,
        )
    )
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


def _ini_values(*, text: str, ini: Path) -> dict[str, str]:
    """Each line one known key, once: `path`, `path.rel` and the two harmless ones."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(INI_SEPARATOR)
        if not separator or key not in INI_KEYS or key in values:
            raise ProtectedTarget(f"{ini} has an unexpected line, the tool target is unknown")
        values[key] = value.strip()
    return values


def _require_ini_pointing_to(*, folder: Path, name: str) -> None:
    """avdmanager deletes the folder the .ini names: it must be the checked one, exactly."""
    ini = folder.parent / f"{name}{AVD_INI_SUFFIX}"
    try:
        text = _read_ini(path=ini)
    except OSError as err:
        raise ProtectedTarget(f"{ini} cannot be read, the tool target is unknown") from err
    if len(text) > MAX_INI_BYTES:
        raise ProtectedTarget(f"{ini} is too large to be an AVD .ini")
    values = _ini_values(text=text, ini=ini)
    # path.rel is relative to the Android home, the parent of the AVD folder's directory.
    relative = values.get(INI_RELATIVE_KEY)
    by_relative = relative is None or os.path.normpath(folder.parent.parent / relative) == str(
        folder
    )
    if values.get(INI_PATH_KEY) != str(folder) or not by_relative:
        raise ProtectedTarget(f"{ini} does not point to {folder}")


def run_item_command(
    *, step: PlanStep, control: DiskFsControl, argv: tuple[str, ...], item: CacheItem
) -> StepOutcome:
    """A successful tool must remove the folder; never fall back to filesystem deletion."""
    env = {key: os.environ[key] for key in ("PATH", "LANG", "JAVA_HOME") if key in os.environ}
    env["HOME"] = str(control.home)
    if Path(argv[0]).name == ITEM_TOOLS[CacheKind.ANDROID_AVD]:
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
