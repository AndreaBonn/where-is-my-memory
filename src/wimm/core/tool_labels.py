"""Recognition of developer tools by process name and command line (pure, no I/O).

Only what a process exposes is used: its name, executable and argv. A kind
cluster lives in a ``kindest/node`` container, which is not a process of its
own, so kind is recognized only through the ``kind`` CLI process; minikube
through the ``minikube`` CLI and its qemu or VirtualBox driver process.
"""

from enum import Enum
from itertools import pairwise
from pathlib import PurePosixPath

from wimm.model.raw import RawProcess

from .categorize_tools import process_names
from .cgroup_paths import basename
from .constants import CLI_WRAPPER_NAMES, OPTION_PREFIX


class ToolLabel(Enum):
    VIRTUAL_MACHINE = "virtual_machine"
    ANDROID_EMULATOR = "android_emulator"
    GRADLE_DAEMON = "gradle_daemon"
    KOTLIN_DAEMON = "kotlin_daemon"
    LANGUAGE_SERVER = "language_server"
    KIND_CLUSTER = "kind_cluster"
    MINIKUBE_CLUSTER = "minikube_cluster"


class ToolReason(Enum):
    GUEST_MEMORY = "guest_memory"
    BACKGROUND_BUILD_DAEMON = "background_build_daemon"
    EDITOR_BACKGROUND_SERVICE = "editor_background_service"
    LOCAL_CLUSTER = "local_cluster"


ToolLabelResult = tuple[ToolLabel, ToolReason]

QEMU_PREFIX = "qemu-system-"
VIRTUALBOX_NAMES = ("VBoxHeadless", "VirtualBoxVM")
ANDROID_EMULATOR_NAME = "emulator"
ANDROID_AVD_FLAG = "-avd"
NODE_MODULES = "node_modules"
JAVA_NAME = "java"
GRADLE_DAEMON_CLASS = "org.gradle.launcher.daemon.bootstrap.GradleDaemon"
KOTLIN_DAEMON_CLASS = "org.jetbrains.kotlin.daemon.KotlinCompileDaemon"
JDTLS_CLASS_PREFIX = "org.eclipse.jdt.ls"
LANGUAGE_SERVER_NAMES = (
    "rust-analyzer",
    "gopls",
    "pyright-langserver",
    "pyright",
    "pylsp",
    "typescript-language-server",
    "jdtls",
    "clangd",
)
CLANGD_VERSIONED_PREFIX = "clangd-"
KIND_NAME = "kind"
MINIKUBE_NAME = "minikube"
MINIKUBE_GUEST_PREFIX = "guest=minikube"


def _argv(proc: RawProcess) -> tuple[str, ...]:
    return proc.cmdline or ()


def _is_minikube_guest(args: tuple[str, ...]) -> bool:
    return any(arg == MINIKUBE_NAME or arg.startswith(MINIKUBE_GUEST_PREFIX) for arg in args)


def _is_vm_binary(names: tuple[str, ...]) -> bool:
    return any(name.startswith(QEMU_PREFIX) or name in VIRTUALBOX_NAMES for name in names)


def _is_language_server_name(name: str) -> bool:
    return name in LANGUAGE_SERVER_NAMES or name.startswith(CLANGD_VERSIONED_PREFIX)


def _script_parts(args: tuple[str, ...]) -> tuple[str, ...]:
    """Path components of the script a wrapper (node, python...) runs, or an empty tuple."""
    if not args or basename(args[0]) not in CLI_WRAPPER_NAMES:
        return ()
    script = next((arg for arg in args[1:] if not arg.startswith(OPTION_PREFIX)), "")
    parts = PurePosixPath(script).parts
    # Only the script's own name, or the package folder right under node_modules, names the
    # server: any folder on the way (~/work/gopls/build.js) would be a false positive.
    packages = tuple(part for previous, part in pairwise(parts) if previous == NODE_MODULES)
    stem = (PurePosixPath(script).stem,) if script else ()
    return stem + packages


def _is_jdtls(proc: RawProcess, names: tuple[str, ...]) -> bool:
    return JAVA_NAME in names and any(JDTLS_CLASS_PREFIX in arg for arg in _argv(proc=proc))


def _is_language_server(proc: RawProcess, names: tuple[str, ...]) -> bool:
    if any(_is_language_server_name(name=name) for name in names):
        return True
    parts = _script_parts(args=_argv(proc=proc))
    if any(_is_language_server_name(name=part) for part in parts):
        return True
    return _is_jdtls(proc=proc, names=names)


def tool_label(*, proc: RawProcess) -> ToolLabelResult | None:
    """Name the developer tool a process belongs to, with the reason it matters.

    Parameters
    ----------
    proc : RawProcess
        Process whose name, executable and command line are inspected without I/O.

    Returns
    -------
    tuple of ToolLabel and ToolReason, or None
        Internal keys; the user-facing text is resolved elsewhere. ``None`` when
        the process is not one of the known tools (any other ``java`` included).
    """
    names = process_names(proc=proc)
    args = _argv(proc=proc)
    found = _guest_label(names=names, args=args) or _daemon_label(names=names, args=args)
    if found is not None:
        return found
    if _is_language_server(proc=proc, names=names):
        return ToolLabel.LANGUAGE_SERVER, ToolReason.EDITOR_BACKGROUND_SERVICE
    if KIND_NAME in names:
        return ToolLabel.KIND_CLUSTER, ToolReason.LOCAL_CLUSTER
    if MINIKUBE_NAME in names:
        return ToolLabel.MINIKUBE_CLUSTER, ToolReason.LOCAL_CLUSTER
    return None


def _guest_label(*, names: tuple[str, ...], args: tuple[str, ...]) -> ToolLabelResult | None:
    """Virtual machines, the Android emulator and a minikube guest."""
    if _is_vm_binary(names=names) and _is_minikube_guest(args=args):
        return ToolLabel.MINIKUBE_CLUSTER, ToolReason.LOCAL_CLUSTER
    is_qemu = any(name.startswith(QEMU_PREFIX) for name in names)
    # `emulator` alone is too common a name: the Android one always names its AVD.
    if (ANDROID_EMULATOR_NAME in names or is_qemu) and ANDROID_AVD_FLAG in args:
        return ToolLabel.ANDROID_EMULATOR, ToolReason.GUEST_MEMORY
    if _is_vm_binary(names=names):
        return ToolLabel.VIRTUAL_MACHINE, ToolReason.GUEST_MEMORY
    return None


def _daemon_label(*, names: tuple[str, ...], args: tuple[str, ...]) -> ToolLabelResult | None:
    """Gradle and Kotlin build daemons, recognised by their main class on a JVM."""
    if JAVA_NAME in names and GRADLE_DAEMON_CLASS in args:
        return ToolLabel.GRADLE_DAEMON, ToolReason.BACKGROUND_BUILD_DAEMON
    if JAVA_NAME in names and KOTLIN_DAEMON_CLASS in args:
        return ToolLabel.KOTLIN_DAEMON, ToolReason.BACKGROUND_BUILD_DAEMON
    return None
