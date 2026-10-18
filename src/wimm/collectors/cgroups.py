import logging
import re
from pathlib import Path

from wimm.core.constants import PODMAN_SCOPE_TEMPLATE, USER_UNIT_TEMPLATE

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
PROC_ROOT = Path("/proc")
CGROUP_V2_PREFIX = "0::"
DOCKER_SCOPE = re.compile(r"(?:/sys/fs/cgroup)?/system\.slice/docker-[^/]+\.scope(?:/.*)?")
CONTAINER_ID_PATTERN = re.compile(r"[0-9a-fA-F]+")
STAT_PGRP_INDEX = 2
STAT_TPGID_INDEX = 5


def parse_proc_cgroup(text: str) -> str:
    for line in text.splitlines():
        if line.startswith(CGROUP_V2_PREFIX):
            path = line.removeprefix(CGROUP_V2_PREFIX)
            if path.startswith("/"):
                return path
    raise ValueError("Missing unified cgroup path")


def parse_proc_stat(text: str) -> tuple[int | None, int | None]:
    """Extract process and terminal foreground groups after the last comm parenthesis.

    Parameters
    ----------
    text : str
        Linux /proc/PID/stat contents, including a possibly parenthesized comm.

    Returns
    -------
    tuple[int | None, int | None]
        pgrp and tpgid, with negative kernel sentinels represented as None.
    """
    _, delimiter, suffix = text.rpartition(")")
    fields = suffix.split()
    if not delimiter or len(fields) <= STAT_TPGID_INDEX:
        raise ValueError("Incomplete process stat")
    pgrp, tpgid = int(fields[STAT_PGRP_INDEX]), int(fields[STAT_TPGID_INDEX])
    return (pgrp if pgrp >= 0 else None), (tpgid if tpgid >= 0 else None)


def is_docker_scope(path: str) -> bool:
    return DOCKER_SCOPE.fullmatch(path) is not None


def collect_process_cgroup(pid: int, proc_root: Path = PROC_ROOT) -> CollectorResult[str | None]:
    try:
        text = (proc_root / str(pid) / "cgroup").read_text()
        return CollectorResult(data=parse_proc_cgroup(text=text))
    except Exception as error:
        level = (
            logging.DEBUG
            if isinstance(error, (FileNotFoundError, ProcessLookupError))
            else logging.WARNING
        )
        LOGGER.log(level, "Cgroup collection failed for PID %s: %s", pid, error)
        return CollectorResult(data=None, error=str(error))


def collect_process_stat(
    pid: int, proc_root: Path = PROC_ROOT
) -> CollectorResult[tuple[int | None, int | None] | None]:
    try:
        text = (proc_root / str(pid) / "stat").read_text()
        return CollectorResult(data=parse_proc_stat(text=text))
    except Exception as error:
        level = (
            logging.DEBUG
            if isinstance(error, (FileNotFoundError, ProcessLookupError))
            else logging.WARNING
        )
        LOGGER.log(level, "Process stat collection failed for PID %s: %s", pid, error)
        return CollectorResult(data=None, error=str(error))


CGROUP_ROOT = Path("/sys/fs/cgroup")
CONTAINER_ROOTS = (CGROUP_ROOT, PROC_ROOT)
NET_TX_INDEX = 8


def _stat_value(text: str, key: str) -> int:
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == key:
            return int(fields[1])
    raise ValueError(f"Missing {key}")


def parse_memory_stat(text: str) -> int:
    """Read inactive file bytes.

    Parameters
    ----------
    text : str
        Cgroup v2 memory.stat contents.

    Returns
    -------
    int
        Inactive file bytes.
    """
    return _stat_value(text=text, key="inactive_file")


def parse_cpu_stat(text: str) -> int:
    """Read cumulative CPU use.

    Parameters
    ----------
    text : str
        Cgroup v2 cpu.stat contents.

    Returns
    -------
    int
        Cumulative CPU microseconds.
    """
    return _stat_value(text=text, key="usage_usec")


def parse_net_dev(text: str) -> int:
    """Sum received and transmitted bytes excluding loopback.

    Parameters
    ----------
    text : str
        Linux net/dev contents.

    Returns
    -------
    int
        Total network bytes.
    """
    total = 0
    for line in text.splitlines():
        interface, delimiter, counters = line.partition(":")
        if delimiter and interface.strip() != "lo":
            fields = counters.split()
            total += int(fields[0]) + int(fields[NET_TX_INDEX])
    return total


def locate_container_cgroup(
    container_id: str, pid: int, roots: tuple[Path, Path] = CONTAINER_ROOTS
) -> Path | None:
    """Locate a Docker cgroup, falling back to the process unified membership.

    Parameters
    ----------
    container_id : str
        Full container identifier.
    pid : int
        Container init PID.
    roots : tuple[Path, Path]
        Cgroup and proc filesystem roots.

    Returns
    -------
    Path | None
        Existing cgroup directory, if accessible.
    """
    cgroup_root, proc_root = roots
    standard = cgroup_root / "system.slice" / f"docker-{container_id}.scope"
    if standard.is_dir():
        return standard
    result = collect_process_cgroup(pid=pid, proc_root=proc_root)
    if result.data is None:
        return None
    candidate = cgroup_root / result.data.lstrip("/")
    return candidate if candidate.is_dir() else None


def read_container_metrics(
    container_id: str,
    pid: int,
    roots: tuple[Path, Path] = CONTAINER_ROOTS,
    read_net: bool = True,
) -> tuple[int, int, int | None] | None:
    """Read container memory, CPU and network counters.

    Parameters
    ----------
    container_id : str
        Full container identifier.
    pid : int
        Container init PID.
    roots : tuple[Path, Path]
        Cgroup and proc filesystem roots.
    read_net : bool
        False for host networking, where the PID's counters are the host's.

    Returns
    -------
    tuple[int, int, int | None] | None
        Working set bytes, CPU microseconds and network bytes (None when not
        measured), or None when unavailable.
    """
    scope = locate_container_cgroup(container_id=container_id, pid=pid, roots=roots)
    if scope is None:
        return None
    return _read_container_files(scope=scope, pid=pid if read_net else None, proc_root=roots[1])


def _read_container_files(
    scope: Path, pid: int | None, proc_root: Path
) -> tuple[int, int, int | None] | None:
    try:
        memory = int((scope / "memory.current").read_text())
        inactive = parse_memory_stat(text=(scope / "memory.stat").read_text())
        cpu = parse_cpu_stat(text=(scope / "cpu.stat").read_text())
        net = (
            None
            if pid is None
            else parse_net_dev(text=(proc_root / str(pid) / "net/dev").read_text())
        )
        return max(0, memory - inactive), cpu, net
    except (OSError, ValueError, IndexError) as error:
        LOGGER.debug("Container metrics unavailable at %s: %s", scope, error)
        return None


def locate_libpod_scope(
    container_id: str, uid: int, cgroup_root: Path = CGROUP_ROOT
) -> Path | None:
    """Locate the cgroup of a rootless podman container under the user's systemd manager.

    Parameters
    ----------
    container_id : str
        Hexadecimal container identifier (full or abbreviated); anything else yields None.
    uid : int
        Owner of the rootless podman, whose `user@<uid>.service` is searched.
    cgroup_root : Path
        Cgroup v2 mount point.

    Returns
    -------
    Path | None
        The `libpod-<id>.scope` directory, if present. The conmon scope is not a match.
    """
    if CONTAINER_ID_PATTERN.fullmatch(container_id) is None:
        return None
    manager = cgroup_root / f"user.slice/user-{uid}.slice" / USER_UNIT_TEMPLATE.format(uid=uid)
    name = PODMAN_SCOPE_TEMPLATE.format(container_id=container_id)
    try:
        return next((path for path in manager.rglob(name) if path.is_dir()), None)
    except OSError as error:
        LOGGER.debug("Podman scope search failed under %s: %s", manager, error)
        return None
