import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

import docker

from wimm.model.enums import MetricsSource
from wimm.model.raw import Mount, RawContainer
from wimm.model.snapshot import DockerStatus

from . import CollectorResult
from .cgroups import CONTAINER_ROOTS, read_container_metrics

LOGGER = logging.getLogger(__name__)
STATS_INTERVAL_S = 300.0
STATS_WORKERS = 4
NANOSECONDS_PER_MICROSECOND = 1000
DOCKER_TIMEOUT_S = 5
HOST_NETWORK_MODE = "host"
type Metrics = tuple[int, int, int | None]
UNAVAILABLE_METRICS: Metrics = (0, 0, None)


class ContainerReader(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def attrs(self) -> dict[str, Any]: ...

    def stats(self, *, stream: bool) -> dict[str, Any]: ...


class ContainerListReader(Protocol):
    def list(self, *, all: bool) -> Sequence[ContainerReader]: ...


class DockerReader(Protocol):
    @property
    def containers(self) -> ContainerListReader: ...


@dataclass(frozen=True, slots=True)
class DockerSample:
    status: DockerStatus
    containers: tuple[RawContainer, ...]


def _stats_metrics(stats: dict[str, Any], host_network: bool) -> Metrics:
    memory = stats.get("memory_stats", {})
    inactive = memory.get("stats", {}).get("inactive_file", 0)
    cpu = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    network = sum(
        int(counters.get("rx_bytes", 0)) + int(counters.get("tx_bytes", 0))
        for name, counters in stats.get("networks", {}).items()
        if name != "lo"
    )
    return (
        max(0, int(memory.get("usage", 0)) - int(inactive)),
        int(cpu) // NANOSECONDS_PER_MICROSECOND,
        None if host_network else network,
    )


def _metadata(container: ContainerReader, metrics: Metrics, source: MetricsSource) -> RawContainer:
    attrs = container.attrs
    config, state = attrs.get("Config", {}), attrs.get("State", {})
    return RawContainer(
        id=container.id,
        name=str(attrs.get("Name", container.id)).lstrip("/"),
        image=str(config.get("Image") or attrs.get("Image", "")),
        state=str(state.get("Status", "unknown")),
        labels=tuple(sorted((config.get("Labels") or {}).items())),
        mounts=_mounts(container_id=container.id, attrs=attrs),
        ports=_ports(container_id=container.id, attrs=attrs),
        pid=int(state.get("Pid", 0)),
        memory_bytes=metrics[0],
        cpu_usage_usec=metrics[1],
        net_bytes=metrics[2],
        metrics_source=source,
    )


def _mounts(container_id: str, attrs: dict[str, Any]) -> tuple[Mount, ...]:
    mounts = []
    for item in attrs.get("Mounts") or []:
        try:
            mounts.append(
                Mount(type=item["Type"], source=item["Source"], destination=item["Destination"])
            )
        except (KeyError, TypeError, ValueError) as error:
            LOGGER.warning("Skipping malformed mount of container %s: %r", container_id, error)
    return tuple(mounts)


def _ports(container_id: str, attrs: dict[str, Any]) -> tuple[int, ...]:
    ports: set[int] = set()
    published = (attrs.get("NetworkSettings") or {}).get("Ports") or {}
    for bindings in published.values():
        for binding in bindings or []:
            try:
                ports.add(int(binding["HostPort"]))
            except (KeyError, TypeError, ValueError) as error:
                LOGGER.warning("Skipping malformed port of container %s: %r", container_id, error)
    return tuple(sorted(ports))


def _is_host_network(attrs: dict[str, Any]) -> bool:
    return (attrs.get("HostConfig") or {}).get("NetworkMode") == HOST_NETWORK_MODE


class DockerSource:
    def __init__(
        self,
        reader: DockerReader | None = None,
        roots: tuple[Path, Path] = CONTAINER_ROOTS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._reader = reader
        self._roots = roots
        self._clock = clock
        self._available: bool | None = None
        self._cache: dict[str, tuple[float, Metrics | None]] = {}

    def collect(self) -> CollectorResult[DockerSample]:
        """Sample Docker metadata and counters without modifying daemon resources.

        Returns
        -------
        CollectorResult[DockerSample]
            Availability with a readable error, and immutable container samples.
        """
        try:
            sample = self._sample()
            self._available = True
            return CollectorResult(data=sample)
        except Exception as error:
            reason = str(error) or type(error).__name__
            if self._available is not False:
                LOGGER.warning("Docker unavailable: %s", reason)
            self._available = False
            return CollectorResult(
                data=DockerSample(
                    status=DockerStatus(available=False, error=reason),
                    containers=(),
                ),
                error=reason,
            )

    def _sample(self) -> DockerSample:
        if self._reader is None:
            self._reader = docker.from_env(timeout=DOCKER_TIMEOUT_S)
        containers = self._reader.containers.list(all=True)
        identifiers = {container.id for container in containers}
        self._cache = {key: value for key, value in self._cache.items() if key in identifiers}
        with ThreadPoolExecutor(max_workers=STATS_WORKERS) as executor:
            samples = tuple(executor.map(self._collect_safely, containers))
        kept = tuple(item for item in samples if item is not None)
        return DockerSample(status=DockerStatus(available=True, error=None), containers=kept)

    def _collect_safely(self, container: ContainerReader) -> RawContainer | None:
        try:
            return self._collect_container(container=container)
        except Exception as error:
            LOGGER.warning("Skipping container %s: %r", container.id, error)
            return None

    def _collect_container(self, container: ContainerReader) -> RawContainer:
        state = container.attrs.get("State", {})
        if state.get("Status") != "running":
            self._cache.pop(container.id, None)
            return _metadata(
                container=container, metrics=UNAVAILABLE_METRICS, source=MetricsSource.UNAVAILABLE
            )
        pid = int(state.get("Pid") or 0)
        metrics = None
        if pid > 0:
            metrics = read_container_metrics(
                container_id=container.id,
                pid=pid,
                roots=self._roots,
                read_net=not _is_host_network(attrs=container.attrs),
            )
        if metrics is not None:
            return _metadata(container=container, metrics=metrics, source=MetricsSource.CGROUP)
        metrics = self._fallback(container=container)
        source = MetricsSource.STATS_API if metrics is not None else MetricsSource.UNAVAILABLE
        return _metadata(container=container, metrics=metrics or UNAVAILABLE_METRICS, source=source)

    def _fallback(self, container: ContainerReader) -> Metrics | None:
        now = self._clock()
        cached = self._cache.get(container.id)
        if cached is not None and now - cached[0] < STATS_INTERVAL_S:
            return cached[1]
        metrics = None
        try:
            metrics = _stats_metrics(
                stats=container.stats(stream=False),
                host_network=_is_host_network(attrs=container.attrs),
            )
        except Exception as error:
            LOGGER.debug("Docker stats unavailable for %s: %s", container.id, error)
        self._cache[container.id] = (now, metrics)
        return metrics
