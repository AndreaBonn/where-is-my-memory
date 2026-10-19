import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

from wimm.core.docker_notices import EngineNotice, NoticeCode, notices_text
from wimm.model.enums import MetricsSource
from wimm.model.raw import Mount, RawContainer
from wimm.model.snapshot import DockerStatus

from . import CollectorResult
from .cgroups import CONTAINER_ROOTS, read_container_metrics
from .docker_engines import Engine, EngineProvider, FixedEngines, local_pool
from .docker_stats import Metrics, StatsSampler, is_host_network

LOGGER = logging.getLogger(__name__)
DOCKER_TIMEOUT_S = 5
UNAVAILABLE_METRICS: Metrics = (0, 0, None)


class ContainerReader(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def attrs(self) -> dict[str, Any]: ...

    def stats(self, *, stream: bool) -> dict[str, Any]: ...


class ContainerListReader(Protocol):
    def list(self, *, all: bool, ignore_removed: bool) -> Sequence[ContainerReader]: ...


class DockerReader(Protocol):
    @property
    def containers(self) -> ContainerListReader: ...


@dataclass(frozen=True, slots=True)
class DockerSample:
    status: DockerStatus
    containers: tuple[RawContainer, ...]
    notices: tuple[EngineNotice, ...] = ()

    def container_ids(self, *, answered: bool) -> frozenset[str]:
        """Full ids the engine listed; empty if it did not answer (Podman stays protected)."""
        return frozenset(item.id for item in self.containers) if answered else frozenset()


def _metadata(
    *, container: ContainerReader, metrics: Metrics, source: MetricsSource
) -> RawContainer:
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


def _mounts(*, container_id: str, attrs: dict[str, Any]) -> tuple[Mount, ...]:
    mounts = []
    for item in attrs.get("Mounts") or []:
        try:
            mounts.append(
                Mount(type=item["Type"], source=item["Source"], destination=item["Destination"])
            )
        except (KeyError, TypeError, ValueError) as error:
            LOGGER.warning("Skipping malformed mount of container %s: %r", container_id, error)
    return tuple(mounts)


def _ports(*, container_id: str, attrs: dict[str, Any]) -> tuple[int, ...]:
    ports: set[int] = set()
    published = (attrs.get("NetworkSettings") or {}).get("Ports") or {}
    for bindings in published.values():
        for binding in bindings or []:
            try:
                ports.add(int(binding["HostPort"]))
            except (KeyError, TypeError, ValueError) as error:
                LOGGER.warning("Skipping malformed port of container %s: %r", container_id, error)
    return tuple(sorted(ports))


def _list_containers(
    *, provider: EngineProvider, engines: Sequence[Engine], notices: list[EngineNotice]
) -> list[ContainerReader] | None:
    """Every engine's containers, or None when no engine answered."""
    listed: list[ContainerReader] = []
    answered = False
    for engine in engines:
        try:
            # A container removed between listing and inspection is skipped, not fatal.
            listed.extend(engine.client.containers.list(all=True, ignore_removed=True))
        except Exception as error:
            provider.discard(engine=engine)
            detail = str(error) or type(error).__name__
            notices.append(
                EngineNotice(
                    code=NoticeCode.UNREACHABLE, endpoint=engine.identity.path, detail=detail
                )
            )
            continue
        answered = True
    return listed if answered else None


class DockerSource:
    """Containers of every reachable engine; one engine failing never hides the others."""

    def __init__(
        self,
        reader: DockerReader | None = None,
        roots: tuple[Path, Path] = CONTAINER_ROOTS,
        clock: Callable[[], float] = monotonic,
        engines: EngineProvider | None = None,
    ) -> None:
        self._engines = engines or (FixedEngines(client=reader) if reader is not None else None)
        self._roots = roots
        self._stats = StatsSampler(clock=clock)
        self._problem: str | None = None

    def collect(self) -> CollectorResult[DockerSample]:
        """Sample Docker metadata and counters without modifying daemon resources.

        Returns
        -------
        CollectorResult[DockerSample]
            Availability with a readable error, immutable container samples, and the notices
            about engines that were refused or did not answer.
        """
        try:
            return self._collect()
        except Exception as error:
            return self._unavailable(notices=(), reason=str(error) or type(error).__name__)

    def _collect(self) -> CollectorResult[DockerSample]:
        started = monotonic()
        if self._engines is None:
            self._engines = local_pool(timeout=DOCKER_TIMEOUT_S)
        provider = self._engines
        view = provider.refresh()
        notices = list(view.notices)
        listed = _list_containers(provider=provider, engines=view.engines, notices=notices)
        if listed is None:
            return self._unavailable(notices=tuple(notices), reason=notices_text(notices=notices))
        containers = self._read_containers(listed=listed)
        self._stats.retain(ids=frozenset(item.id for item in listed))
        self._warn_on_change(problem=notices_text(notices=notices))
        elapsed = monotonic() - started
        LOGGER.debug("Docker sample: %d containers in %.3f s", len(containers), elapsed)
        return CollectorResult(
            data=DockerSample(
                status=DockerStatus(available=True, error=None),
                containers=containers,
                notices=tuple(notices),
            )
        )

    def _unavailable(
        self, *, notices: tuple[EngineNotice, ...], reason: str
    ) -> CollectorResult[DockerSample]:
        reason = reason or notices_text(notices=[EngineNotice(NoticeCode.NO_ENGINE, endpoint="")])
        self._warn_on_change(problem=reason)
        return CollectorResult(
            data=DockerSample(
                status=DockerStatus(available=False, error=reason), containers=(), notices=notices
            ),
            error=reason,
        )

    def _warn_on_change(self, *, problem: str) -> None:
        if problem and problem != self._problem:
            LOGGER.warning("Docker: %s", problem)
        self._problem = problem or None

    def _read_containers(self, *, listed: Sequence[ContainerReader]) -> tuple[RawContainer, ...]:
        """Cgroup reads first, one by one; then the stats API for those without a cgroup."""
        ready: dict[str, RawContainer] = {}
        waiting: list[ContainerReader] = []
        for container in listed:
            try:
                self._read_cgroup_phase(container=container, ready=ready, waiting=waiting)
            except Exception as error:
                LOGGER.warning("Skipping container %s: %r", container.id, error)
        readings = self._stats.sample(containers=waiting)
        for container in waiting:
            try:
                metrics = readings.get(container.id)
                source = MetricsSource.STATS_API if metrics else MetricsSource.UNAVAILABLE
                ready[container.id] = _metadata(
                    container=container, metrics=metrics or UNAVAILABLE_METRICS, source=source
                )
            except Exception as error:
                LOGGER.warning("Skipping container %s: %r", container.id, error)
        return tuple(ready[item.id] for item in listed if item.id in ready)

    def _read_cgroup_phase(
        self,
        *,
        container: ContainerReader,
        ready: dict[str, RawContainer],
        waiting: list[ContainerReader],
    ) -> None:
        state = container.attrs.get("State", {})
        if state.get("Status") != "running":
            self._stats.forget(container_id=container.id)
            unavailable = UNAVAILABLE_METRICS
            ready[container.id] = _metadata(
                container=container, metrics=unavailable, source=MetricsSource.UNAVAILABLE
            )
            return
        pid = int(state.get("Pid") or 0)
        metrics = None
        if pid > 0:
            metrics = read_container_metrics(
                container_id=container.id,
                pid=pid,
                roots=self._roots,
                read_net=not is_host_network(attrs=container.attrs),
            )
        if metrics is None:
            waiting.append(container)
        else:
            ready[container.id] = _metadata(
                container=container, metrics=metrics, source=MetricsSource.CGROUP
            )
