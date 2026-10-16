import logging
import re
from pathlib import Path

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
PROC_ROOT = Path("/proc")
CGROUP_V2_PREFIX = "0::"
DOCKER_SCOPE = re.compile(r"(?:/sys/fs/cgroup)?/system\.slice/docker-[^/]+\.scope(?:/.*)?")
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
