"""Real implementations of the executor's controls on psutil and the Docker SDK."""

import logging
import os
import signal
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Protocol

import docker
import docker.errors
import psutil

from wimm.collectors.processes import collect_processes
from wimm.core.categorize import CategorizationContext, categorize_process
from wimm.model.enums import Protection, protection_of

from .control_protocols import LiveContainer, LiveProcess
from .controls_disk import DiskClientLike, DiskSdkOps
from .errors import ControlFailed

LOGGER = logging.getLogger(__name__)
MISSING = (psutil.NoSuchProcess, psutil.ZombieProcess)


class _SelectedProcesses:
    """`ProcessReader` yielding only the given pids, with the attributes the collector reads."""

    def __init__(self, *, pids: Iterable[int]) -> None:
        self._pids = tuple(pids)

    def process_iter(self, attrs: list[str]) -> Iterable[psutil.Process]:
        for pid in self._pids:
            try:
                process = psutil.Process(pid)
                process.info = process.as_dict(attrs=attrs)
            except MISSING:
                continue
            yield process


class PsutilProcessControl:
    """Process control on psutil; remembers the `psutil.Process` of what it inspected.

    Signals go through the remembered object, which psutil refuses to use once the PID
    was reused, so a recycled PID is never signalled.
    """

    def __init__(self, *, owner_uid: int, extra_protected_names: tuple[str, ...] = ()) -> None:
        self._owner_uid = owner_uid
        self._extra_protected_names = extra_protected_names
        self._known: dict[int, psutil.Process] = {}

    def set_extra_protected_names(self, *, names: tuple[str, ...]) -> None:
        self._extra_protected_names = names

    def inspect(self, *, pid: int) -> LiveProcess | None:
        try:
            process = psutil.Process(pid)
            live = LiveProcess(
                pid=pid,
                create_time=process.create_time(),
                uid=int(process.uids().real),
                cmdline=self._cmdline(process=process),
                protected=self._is_protected(process=process),
            )
        except MISSING:
            return None
        except psutil.Error as error:
            raise ControlFailed(f"Cannot inspect process {pid}: {error}") from error
        self._known[pid] = process
        return live

    def self_lineage(self) -> frozenset[int]:
        me = psutil.Process(os.getpid())
        return frozenset([me.pid, *(parent.pid for parent in me.parents())])

    def descendants(self, *, pid: int) -> Sequence[int]:
        try:
            process = self._known.get(pid) or psutil.Process(pid)
            children = process.children(recursive=True)
        except MISSING:
            return ()
        except psutil.Error as error:
            raise ControlFailed(f"Cannot list children of {pid}: {error}") from error
        self._known.update({child.pid: child for child in children})
        return [child.pid for child in children]

    def send_signal(self, *, pid: int, sig: signal.Signals) -> None:
        process = self._known.get(pid)
        if process is None:
            raise ControlFailed(f"Process {pid} was not inspected before signalling")
        try:
            process.send_signal(sig)
        except MISSING:
            return
        except psutil.Error as error:
            raise ControlFailed(f"Cannot signal process {pid}: {error}") from error

    def wait_gone(self, *, pids: Sequence[int], timeout_s: float) -> frozenset[int]:
        processes = [self._known[pid] for pid in pids if pid in self._known]
        _, alive = psutil.wait_procs(processes, timeout=timeout_s)
        return frozenset(process.pid for process in alive)

    @staticmethod
    def _cmdline(*, process: psutil.Process) -> tuple[str, ...]:
        try:
            return tuple(process.cmdline())
        except psutil.AccessDenied:
            return ()

    def _is_protected(self, *, process: psutil.Process) -> bool:
        """Re-categorize with the same rules as the sampler; unknown means protected."""
        chain = [process.pid, *(parent.pid for parent in process.parents())]
        raw = collect_processes(source=_SelectedProcesses(pids=chain), own_uid=self._owner_uid)
        by_pid = {item.pid: item for item in raw.data}
        target = by_pid.get(process.pid)
        if target is None or len(by_pid) < len(chain):
            LOGGER.debug("Chain of process %d incomplete, treated as protected", process.pid)
            return True
        context = CategorizationContext(
            own_uid=self._owner_uid,
            own_pid=os.getpid(),
            processes=by_pid,
            listen_ports_by_pid={},
            extra_protected_names=self._extra_protected_names,
            desktop_categories={},
        )
        category = categorize_process(target, context).category
        return category is None or protection_of(category=category) is Protection.PROTECTED


@contextmanager
def _sdk_errors(*, action: str) -> Iterator[None]:
    """A container that vanished is not an error; other SDK failures become `ControlFailed`."""
    try:
        yield
    except docker.errors.NotFound:
        return
    except (docker.errors.DockerException, OSError) as error:
        raise ControlFailed(f"Cannot {action} container: {error}") from error


class _ContainerLike(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def status(self) -> str: ...

    def stop(self, *, timeout: int) -> None: ...

    def start(self) -> None: ...

    def remove(self, *, v: bool) -> None: ...


class _ContainerCollection(Protocol):
    def get(self, container_id: str) -> _ContainerLike: ...


class DockerClientLike(DiskClientLike, Protocol):
    @property
    def containers(self) -> _ContainerCollection: ...


class DockerSdkControl(DiskSdkOps):
    """Docker control on the SDK (containers here, disk objects in `DiskSdkOps`).

    SDK failures become `ControlFailed`.
    """

    _client: DockerClientLike

    def __init__(self, *, client: DockerClientLike) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "DockerSdkControl":
        client: Any = docker.from_env()
        return cls(client=client)

    def inspect(self, *, container_id: str) -> LiveContainer | None:
        with _sdk_errors(action="inspect"):
            container = self._client.containers.get(container_id)
            return LiveContainer(id=container.id, status=container.status)
        return None

    def stop(self, *, container_id: str, timeout_s: int) -> None:
        with _sdk_errors(action="stop"):
            self._client.containers.get(container_id).stop(timeout=timeout_s)

    def start(self, *, container_id: str) -> None:
        with _sdk_errors(action="start"):
            self._client.containers.get(container_id).start()

    def remove(self, *, container_id: str, volumes: bool) -> None:
        with _sdk_errors(action="remove"):
            self._client.containers.get(container_id).remove(v=volumes)
