from __future__ import annotations

import logging
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic

from wimm.collectors import CollectorResult
from wimm.collectors.docker_source import DockerSample
from wimm.collectors.foreground import ForegroundState, ForegroundStatus
from wimm.collectors.sockets import (
    Quadruple,
    connections_from_index,
    listening_ports_by_pid,
    non_listening_port_index,
)
from wimm.core.activity import EntitySample
from wimm.core.assemble import SystemState
from wimm.core.grouping import GroupDraft
from wimm.core.memory import NO_KERNEL_MEMORY
from wimm.model.enums import MetricsSource
from wimm.model.memory import DiskUsage
from wimm.model.raw import MemInfo, RawContainer, RawProcess, RawSocket
from wimm.model.snapshot import DockerStatus

from .history import MAX_MISSED_CYCLES, EntityKey
from .sampler_collectors import Collectors, ForegroundSource, safe_read

LOGGER = logging.getLogger(__name__)
MICROSECONDS_PER_SECOND = 1_000_000


def identity(*, proc: RawProcess) -> tuple[int, float] | None:
    if proc.create_time is None:
        return None
    return proc.pid, proc.create_time


def children_by_pid(*, processes: Mapping[int, RawProcess]) -> dict[int, tuple[int, ...]]:
    children: dict[int, list[int]] = {}
    for proc in processes.values():
        if proc.ppid != proc.pid:
            children.setdefault(proc.ppid, []).append(proc.pid)
    return {pid: tuple(values) for pid, values in children.items()}


def family_pids(*, pid: int, children: Mapping[int, tuple[int, ...]]) -> frozenset[int]:
    pending = deque([pid])
    family: set[int] = set()
    while pending:
        current = pending.popleft()
        if current not in family:
            family.add(current)
            pending.extend(children.get(current, ()))
    return frozenset(family)


def post_order(
    *, pids: tuple[int, ...], children: Mapping[int, tuple[int, ...]]
) -> tuple[int, ...]:
    visited: set[int] = set()
    order: list[int] = []
    for pid in pids:
        pending = [(pid, False)]
        while pending:
            current, expanded = pending.pop()
            if expanded:
                order.append(current)
            elif current not in visited:
                visited.add(current)
                pending.append((current, True))
                pending.extend((child, False) for child in children.get(current, ()))
    return tuple(order)


def cpu_deltas(
    *, processes: Mapping[int, RawProcess], previous: Mapping[int, RawProcess]
) -> dict[int, float]:
    deltas: dict[int, float] = {}
    for pid, current in processes.items():
        old = previous.get(pid)
        if old is None or identity(proc=current) is None:
            continue
        if identity(proc=current) != identity(proc=old):
            continue
        if current.cpu_time_s is not None and old.cpu_time_s is not None:
            deltas[pid] = max(0.0, current.cpu_time_s - old.cpu_time_s)
    return deltas


def subtree_cpu(
    *, order: tuple[int, ...], children: Mapping[int, tuple[int, ...]], deltas: Mapping[int, float]
) -> dict[int, float]:
    totals: dict[int, float] = {}
    for pid in order:
        totals[pid] = deltas.get(pid, 0.0) + sum(
            totals.get(child, 0.0) for child in children.get(pid, ())
        )
    return totals


def docker_status(docker: CollectorResult[DockerSample]) -> DockerStatus:
    if docker.error:
        return DockerStatus(available=False, error=docker.error)
    return docker.data.status


def read_foreground(*, reader: ForegroundSource) -> ForegroundState:
    """Read the foreground window once, logging how long xprop took."""
    started = monotonic()
    state = reader.read()
    LOGGER.debug("Foreground read %.6f s, status %s", monotonic() - started, state.status)
    return state


def container_sample(*, item: RawContainer, now: datetime) -> EntitySample:
    unavailable = item.metrics_source is MetricsSource.UNAVAILABLE
    return EntitySample(
        taken_at=now,
        cpu_time_s=None if unavailable else item.cpu_usage_usec / MICROSECONDS_PER_SECOND,
        net_bytes=item.net_bytes,
    )


def foreground_group_pids(
    *, state: ForegroundState, drafts: Sequence[GroupDraft], processes: Mapping[int, RawProcess]
) -> frozenset[int] | None:
    """PIDs of the group owning the foreground window; None when nothing was read.

    The window owner may be a child of a member (``_NET_WM_PID`` is not always the main
    process), so the parent chain is followed until a grouped process is found. A window of
    a process in no group yields an empty set: nothing tracked is in the foreground. A pid
    that is not a known process (a sandbox namespace, e.g. Flatpak) is unknown: None.
    """
    if state.status is not ForegroundStatus.ACTIVE or state.pid is None:
        return None
    if state.pid not in processes:
        return None
    pid: int | None = state.pid
    seen: set[int] = set()
    while pid is not None and pid not in seen:
        seen.add(pid)
        for draft in drafts:
            if pid in draft.process_pids:
                return frozenset(draft.process_pids)
        owner = processes.get(pid)
        pid = None if owner is None else owner.ppid
    return frozenset()


def family_ports(*, pids: frozenset[int], ports: Mapping[int, frozenset[int]]) -> frozenset[int]:
    return frozenset(port for pid in pids for port in ports.get(pid, ()))


class ProcessSamples:
    def __init__(self) -> None:
        self.previous: dict[int, RawProcess] = {}
        self.totals: dict[EntityKey, float] = {}
        self._deltas: dict[int, float] = {}
        self._missed: dict[int, int] = {}

    def prepare(self, *, cycle: ProcessCycle) -> None:
        self._deltas = subtree_cpu(
            order=cycle.order,
            children=cycle.children,
            deltas=cpu_deltas(processes=cycle.processes, previous=self.previous),
        )

    def cpu_total(self, *, proc: RawProcess) -> float | None:
        key = identity(proc=proc)
        if key is None or proc.cpu_time_s is None:
            return None
        total = self.totals.get(key, 0.0) + self._deltas.get(proc.pid, 0.0)
        self.totals[key] = total
        return total

    def sample(self, *, proc: RawProcess, cycle: ProcessCycle) -> EntitySample:
        ports = cycle.subtree_ports[proc.pid]
        return EntitySample(
            taken_at=cycle.now,
            cpu_time_s=self.cpu_total(proc=proc),
            foreground=None if cycle.foreground_pids is None else proc.pid in cycle.foreground_pids,
            connections=None
            if cycle.sockets is None
            else connections_from_index(
                index=cycle.connections,
                ports=ports,
            ),
        )

    def finish(self, *, processes: Mapping[int, RawProcess]) -> None:
        for pid in self.previous.keys() | processes.keys():
            self._missed[pid] = 0 if pid in processes else self._missed[pid] + 1
        self.previous.update(processes)
        expired = [pid for pid, missed in self._missed.items() if missed > MAX_MISSED_CYCLES]
        for pid in expired:
            del self.previous[pid]
            del self._missed[pid]
        alive = {identity(proc=proc) for proc in self.previous.values()}
        self.totals = {key: value for key, value in self.totals.items() if key in alive}


@dataclass(frozen=True)
class ProcessCycle:
    processes: Mapping[int, RawProcess]
    ports: Mapping[int, frozenset[int]]
    sockets: tuple[RawSocket, ...] | None
    now: datetime
    foreground_pids: frozenset[int] | None = None
    children: Mapping[int, tuple[int, ...]] = field(init=False)
    order: tuple[int, ...] = field(init=False)
    subtree_ports: Mapping[int, frozenset[int]] = field(init=False)
    connections: Mapping[int, frozenset[Quadruple]] = field(init=False)

    def __post_init__(self) -> None:
        children = children_by_pid(processes=self.processes)
        order = post_order(pids=tuple(self.processes), children=children)
        ports: dict[int, frozenset[int]] = {}
        for pid in order:
            ports[pid] = self.ports.get(pid, frozenset()).union(
                *(ports.get(child, frozenset()) for child in children.get(pid, ()))
            )
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "order", order)
        object.__setattr__(self, "subtree_ports", ports)
        object.__setattr__(
            self, "connections", non_listening_port_index(sockets=self.sockets or ())
        )


class ListenPorts:
    def __init__(self) -> None:
        self._previous: dict[tuple[int, float], frozenset[int]] = {}

    def collect(
        self, *, processes: tuple[RawProcess, ...], sockets: CollectorResult[tuple[RawSocket, ...]]
    ) -> dict[int, frozenset[int]]:
        ports = listening_ports_by_pid(sockets=sockets.data)
        if sockets.error:
            ports = {
                proc.pid: self._previous[key]
                for proc in processes
                if (key := identity(proc=proc)) in self._previous
            }
        self._previous = {
            key: ports[proc.pid]
            for proc in processes
            if (key := identity(proc=proc)) is not None and proc.pid in ports
        }
        return ports


def system_state(
    *,
    collectors: Collectors,
    counters: tuple[MemInfo, tuple[DiskUsage, ...], int],
    docker: DockerStatus,
) -> SystemState:
    """System counters plus the kernel voices, video memory and PSI read this cycle.

    ``counters`` is RAM, disks and the safe-to-free disk bytes.
    """
    mem, disks, reclaimable_disk = counters
    return SystemState(
        mem=mem,
        disks=disks,
        docker=docker,
        reclaimable_disk=reclaimable_disk,
        kernel=safe_read(collectors.kernel_memory, neutral=NO_KERNEL_MEMORY, name="kernel_memory"),
        video=safe_read(collectors.video, neutral=(), name="video"),
        psi=safe_read(collectors.psi, neutral=None, name="psi"),
    )
