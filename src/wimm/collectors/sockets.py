import logging
from collections.abc import Callable, Iterable, Mapping
from ipaddress import IPv6Address
from typing import Protocol

import psutil

from wimm.model.raw import RawSocket

from . import CollectorResult

LOGGER = logging.getLogger(__name__)
TCP_KIND = "tcp"
LISTEN = "LISTEN"
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})
type Quadruple = tuple[str, int, str, int]


class Connection(Protocol):
    @property
    def pid(self) -> int | None: ...

    @property
    def laddr(self) -> tuple[str, int] | tuple[()]: ...

    @property
    def raddr(self) -> tuple[str, int] | tuple[()]: ...

    @property
    def status(self) -> str: ...


def collect_sockets(
    source: Callable[..., Iterable[Connection]] = psutil.net_connections,
) -> CollectorResult[tuple[RawSocket, ...]]:
    try:
        sockets = tuple(
            RawSocket(
                pid=item.pid, laddr=item.laddr or None, raddr=item.raddr or None, status=item.status
            )
            for item in source(kind=TCP_KIND)
        )
        return CollectorResult(data=sockets)
    except Exception as error:
        LOGGER.warning("Socket collection failed: %s", error)
        return CollectorResult(data=(), error=str(error))


def listening_ports_by_pid(sockets: Iterable[RawSocket]) -> dict[int, frozenset[int]]:
    ports: dict[int, set[int]] = {}
    for item in sockets:
        if item.pid is not None and item.status == LISTEN and item.laddr is not None:
            ports.setdefault(item.pid, set()).add(item.laddr[1])
    return {pid: frozenset(values) for pid, values in ports.items()}


def non_listening_by_pid(sockets: Iterable[RawSocket]) -> dict[int, frozenset[Quadruple]]:
    connections: dict[int, set[Quadruple]] = {}
    for item in sockets:
        if item.pid is None or item.status == LISTEN or not item.laddr or not item.raddr:
            continue
        connections.setdefault(item.pid, set()).add((*item.laddr, *item.raddr))
    return {pid: frozenset(values) for pid, values in connections.items()}


def ancestors(pid: int, ppid: Mapping[int, int]) -> set[int]:
    lineage: set[int] = set()
    while pid not in lineage:
        lineage.add(pid)
        if pid not in ppid:
            break
        pid = ppid[pid]
    return lineage


def connections_for_server(
    sockets: tuple[RawSocket, ...], pid: int, ppid: Mapping[int, int]
) -> tuple[RawSocket, ...]:
    """Select non-listening traffic using listeners in the direct process lineage.

    Parameters
    ----------
    sockets : tuple[RawSocket, ...]
        System TCP sample.
    pid : int
        Process whose server traffic is requested.
    ppid : Mapping[int, int]
        Parent PID lookup; siblings do not share listeners.

    Returns
    -------
    tuple[RawSocket, ...]
        Connections on a related listening port, including local client endpoints.
    """
    ports = listening_ports_by_pid(sockets=sockets)
    related = ancestors(pid=pid, ppid=ppid)
    related.update(candidate for candidate in ppid if pid in ancestors(pid=candidate, ppid=ppid))
    server_ports = frozenset(port for owner in related for port in ports.get(owner, ()))
    local_addresses = local_server_addresses(sockets=sockets)
    return tuple(
        item
        for item in sockets
        if matches_server(socket=item, ports=server_ports, addresses=local_addresses)
    )


def matches_server(socket: RawSocket, ports: frozenset[int], addresses: frozenset[str]) -> bool:
    if socket.status == LISTEN or socket.laddr is None or socket.raddr is None:
        return False
    if socket.laddr[1] in ports:
        return True
    return bool(
        socket.raddr
        and normalize_address(address=socket.raddr[0]) in addresses
        and socket.raddr[1] in ports
    )


def normalize_address(address: str) -> str:
    if ":" in address:
        mapped = IPv6Address(address=address).ipv4_mapped
        if mapped is not None:
            return str(mapped)
    return address


def local_server_addresses(sockets: Iterable[RawSocket]) -> frozenset[str]:
    addresses = frozenset(
        normalize_address(address=item.laddr[0]) for item in sockets if item.laddr
    )
    return addresses | LOOPBACK_ADDRESSES


def non_listening_for_ports(
    sockets: tuple[RawSocket, ...], ports: frozenset[int]
) -> frozenset[Quadruple]:
    addresses = local_server_addresses(sockets=sockets)
    return frozenset(
        (*item.laddr, *item.raddr)
        for item in sockets
        if item.laddr is not None
        and item.raddr is not None
        and matches_server(socket=item, ports=ports, addresses=addresses)
    )
