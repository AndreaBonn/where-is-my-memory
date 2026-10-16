import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from time import perf_counter
from typing import Protocol

import psutil

from wimm.model.raw import RawProcess

from . import CollectorResult
from .cgroups import PROC_ROOT, collect_process_cgroup, collect_process_stat, is_docker_scope

LOGGER = logging.getLogger(__name__)
PROCESS_ATTRS = ["pid", "name", "uids", "memory_info"]


class ProcessReader(Protocol):
    def process_iter(self, attrs: list[str]) -> Iterable[psutil.Process]: ...


def _read[T](operation: Callable[[], T]) -> T | None:
    try:
        return operation()
    except psutil.AccessDenied:
        return None


def _collect_owned(process: psutil.Process, uid: int, proc_root: Path) -> RawProcess | None:
    cgroup = collect_process_cgroup(pid=process.pid, proc_root=proc_root).data
    if cgroup is None:
        _skip(process=process, reason="cgroup unreadable")
        return None
    if is_docker_scope(path=cgroup):
        return None
    groups = collect_process_stat(pid=process.pid, proc_root=proc_root).data
    return _build_process(process=process, uid=uid, cgroup=cgroup, groups=groups)


def _collect_foreign(process: psutil.Process, uid: int, proc_root: Path) -> RawProcess | None:
    cgroup = collect_process_cgroup(pid=process.pid, proc_root=proc_root).data
    if cgroup is None:
        _skip(process=process, reason="cgroup unreadable")
        return None
    if is_docker_scope(path=cgroup):
        return None
    ppid = _read(operation=process.ppid)
    rss = _rss(process=process)
    if ppid is None or rss is None:
        _skip(process=process, reason="ppid or rss unreadable")
        return None
    return _foreign_record(process=process, ppid=ppid, rss=rss, cgroup=cgroup)


def _foreign_record(process: psutil.Process, ppid: int, rss: int, cgroup: str) -> RawProcess:
    return RawProcess(
        pid=process.pid,
        ppid=ppid,
        uid=int(process.info["uids"].real),
        name=process.info["name"],
        exe=None,
        cmdline=None,
        cwd=None,
        create_time=None,
        cpu_time_s=None,
        pss=None,
        uss=None,
        swap=None,
        rss=rss,
        cgroup=cgroup,
        terminal=None,
        pgid=None,
        tpgid=None,
    )


def _skip(process: psutil.Process, reason: str) -> None:
    LOGGER.debug("Skipping pid %d: %s", process.pid, reason)


def _build_process(
    process: psutil.Process, uid: int, cgroup: str, groups: tuple[int | None, int | None] | None
) -> RawProcess | None:
    memory = _read(operation=process.memory_full_info)
    rss = int(memory.rss) if memory else _rss(process=process)
    ppid = _read(operation=process.ppid)
    if ppid is None or rss is None:
        _skip(process=process, reason="ppid or rss unreadable")
        return None
    cpu = _read(operation=process.cpu_times)
    cmdline = _read(operation=process.cmdline)
    return RawProcess(
        pid=process.pid,
        ppid=ppid,
        uid=uid,
        name=process.info["name"],
        exe=_read(operation=process.exe),
        cmdline=tuple(cmdline) if cmdline is not None else None,
        cwd=_read(operation=process.cwd),
        create_time=_read(operation=process.create_time),
        cpu_time_s=float(cpu.user + cpu.system) if cpu else None,
        pss=int(memory.pss) if memory else None,
        uss=int(memory.uss) if memory else None,
        swap=int(memory.swap) if memory else None,
        rss=rss,
        cgroup=cgroup,
        terminal=_read(operation=process.terminal),
        pgid=groups[0] if groups else None,
        tpgid=groups[1] if groups else None,
    )


def _rss(process: psutil.Process) -> int | None:
    memory = process.info["memory_info"]
    return int(memory.rss) if memory is not None else None


def _collect_one(process: psutil.Process, own_uid: int, proc_root: Path) -> RawProcess | None:
    uid = process.info["uids"]
    if uid is None or process.info["name"] is None:
        _skip(process=process, reason="uids or name unreadable")
        return None
    if uid.real != own_uid:
        return _collect_foreign(process=process, uid=int(uid.real), proc_root=proc_root)
    return _collect_owned(process=process, uid=int(uid.real), proc_root=proc_root)


def collect_processes(
    source: ProcessReader = psutil, own_uid: int | None = None, proc_root: Path = PROC_ROOT
) -> CollectorResult[tuple[RawProcess, ...]]:
    """Sample processes, preserving readable fields; unreadable processes are skipped.

    Parameters
    ----------
    source : ProcessReader
        Injected psutil-compatible reader.
    own_uid : int | None
        Real user ID; defaults to the current user.
    proc_root : Path
        Proc filesystem root.

    Returns
    -------
    CollectorResult[tuple[RawProcess, ...]]
        Processes and any enumeration error.
    """
    return _scan(
        source=source, own_uid=os.getuid() if own_uid is None else own_uid, proc_root=proc_root
    )


def _scan(
    source: ProcessReader, own_uid: int, proc_root: Path
) -> CollectorResult[tuple[RawProcess, ...]]:
    start = perf_counter()
    processes = []
    errors: set[str] = set()
    try:
        for process in source.process_iter(attrs=PROCESS_ATTRS.copy()):
            try:
                record = _collect_one(process=process, own_uid=own_uid, proc_root=proc_root)
                if record is not None:
                    processes.append(record)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except Exception as error:
                LOGGER.debug("Unexpected error for pid %d", process.pid, exc_info=True)
                errors.add(str(error))
    except Exception as error:
        errors.add(str(error))
        LOGGER.warning("Process enumeration failed: %s", error)
    finally:
        LOGGER.debug("Process collection duration: %.3f ms", (perf_counter() - start) * 1000)
    return CollectorResult(data=tuple(processes), error="; ".join(sorted(errors)) or None)
