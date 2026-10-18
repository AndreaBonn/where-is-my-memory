"""Real implementations of the executor's controls on psutil and the Docker SDK."""

import logging
import os
import signal
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Protocol

import docker
import docker.errors
import psutil

from wimm.collectors.docker_engines import EngineProvider, EngineView
from wimm.collectors.processes import collect_processes
from wimm.core.categorize import CategorizationContext, categorize_process
from wimm.core.docker_notices import notices_text
from wimm.model.enums import Protection, protection_of

from .control_protocols import LiveContainer, LiveProcess
from .controls_disk import DiskClientLike, DiskSdkOps
from .errors import ControlFailed, DockerUnavailable

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
    """Docker control over every local engine (containers here, disk objects in `DiskSdkOps`).

    A container operation goes to the first engine that has the id; disk operations go to the
    primary engine, the first one, as the disk report does. The engines are resolved at each
    call, so Docker started after the app is usable. SDK failures become `ControlFailed`.
    """

    def __init__(self, *, engines: EngineProvider) -> None:
        self._engines = engines

    @property
    def _client(self) -> DockerClientLike:
        client: DockerClientLike = self._view().engines[0].client
        return client

    def inspect(self, *, container_id: str) -> LiveContainer | None:
        container = self._find(container_id=container_id, action="inspect")
        if container is None:
            return None
        with _sdk_errors(action="inspect"):
            return LiveContainer(id=container.id, status=container.status)
        return None

    def stop(self, *, container_id: str, timeout_s: int) -> None:
        container = self._find(container_id=container_id, action="stop")
        if container is not None:
            with _sdk_errors(action="stop"):
                container.stop(timeout=timeout_s)

    def start(self, *, container_id: str) -> None:
        container = self._find(container_id=container_id, action="start")
        if container is not None:
            with _sdk_errors(action="start"):
                container.start()

    def remove(self, *, container_id: str, volumes: bool) -> None:
        container = self._find(container_id=container_id, action="remove")
        if container is not None:
            with _sdk_errors(action="remove"):
                container.remove(v=volumes)

    def _view(self) -> EngineView:
        view = self._engines.refresh()
        if not view.engines:
            raise DockerUnavailable(notices_text(notices=view.notices) or "no container engine")
        return view

    def _find(self, *, container_id: str, action: str) -> _ContainerLike | None:
        """The container on the first engine that has it; None if none of them does."""
        for engine in self._view().engines:
            client: DockerClientLike = engine.client
            try:
                return client.containers.get(container_id)
            except docker.errors.NotFound:
                continue
            except (docker.errors.DockerException, OSError) as error:
                raise ControlFailed(f"Cannot {action} container: {error}") from error
        return None
