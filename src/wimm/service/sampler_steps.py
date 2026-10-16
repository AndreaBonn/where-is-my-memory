from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from wimm.collectors import CollectorResult
from wimm.collectors.sockets import (
    Quadruple,
    connections_from_index,
    listening_ports_by_pid,
    non_listening_port_index,
)
from wimm.core.activity import EntitySample
from wimm.model.raw import RawProcess, RawSocket

from .history import MAX_MISSED_CYCLES, EntityKey


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
