"""Memory from the engine's stats API for containers without a readable cgroup (R18).

``stats(stream=False)`` takes 1 to 2 s per call on a real engine (it waits for the second CPU
sample), so a cycle cannot afford one call per container: RNF-03 is 1.5 s. Each cycle starts
at most `STATS_MAX_PER_CYCLE` calls, the stalest containers first, and waits for them no
longer than `STATS_BUDGET_S`. A call that is still running when the budget ends keeps going
in the background and stores its result for the next cycle.
"""

import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from functools import partial
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)
STATS_INTERVAL_S = 300.0
STATS_WORKERS = 4
STATS_MAX_PER_CYCLE = 4
STATS_BUDGET_S = 0.5
NANOSECONDS_PER_MICROSECOND = 1000
HOST_NETWORK_MODE = "host"
NEVER_SAMPLED = float("-inf")
type Metrics = tuple[int, int, int | None]


class StatsReader(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def attrs(self) -> dict[str, Any]: ...

    def stats(self, *, stream: bool) -> dict[str, Any]: ...


def is_host_network(*, attrs: dict[str, Any]) -> bool:
    return (attrs.get("HostConfig") or {}).get("NetworkMode") == HOST_NETWORK_MODE


def stats_metrics(*, stats: dict[str, Any], host_network: bool) -> Metrics:
    """Memory without the reclaimable page cache, CPU in microseconds and network bytes."""
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


class StatsSampler:
    """Cached stats readings, refreshed a few containers per cycle without blocking it."""

    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Metrics | None]] = {}
        self._inflight: set[str] = set()
        self._pool: ThreadPoolExecutor | None = None

    def retain(self, *, ids: frozenset[str]) -> None:
        """Forget the readings of containers that are gone."""
        with self._lock:
            self._cache = {key: value for key, value in self._cache.items() if key in ids}

    def forget(self, *, container_id: str) -> None:
        """Forget one container's reading, such as when it stops."""
        with self._lock:
            self._cache.pop(container_id, None)

    def sample(self, *, containers: Sequence[StatsReader]) -> dict[str, Metrics | None]:
        """Return the latest reading of each container that has one.

        A container is absent until its first call lands; a failed call is a stored None.
        """
        self._refresh_stalest(containers=containers)
        with self._lock:
            return {c.id: self._cache[c.id][1] for c in containers if c.id in self._cache}

    def _refresh_stalest(self, *, containers: Sequence[StatsReader]) -> None:
        now = self._clock()
        with self._lock:
            due = [c for c in containers if self._is_due(container_id=c.id, now=now)]
            due.sort(key=lambda c: self._cache.get(c.id, (NEVER_SAMPLED, None))[0])
            chosen = due[:STATS_MAX_PER_CYCLE]
            self._inflight.update(c.id for c in chosen)
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=STATS_WORKERS)
        wait(
            [self._pool.submit(partial(self._fetch, container=c)) for c in chosen],
            timeout=STATS_BUDGET_S,
        )

    def _is_due(self, *, container_id: str, now: float) -> bool:
        """No reading yet or one older than the interval, and no call already running."""
        if container_id in self._inflight:
            return False
        cached = self._cache.get(container_id)
        return cached is None or now - cached[0] >= STATS_INTERVAL_S

    def _fetch(self, *, container: StatsReader) -> None:
        metrics = None
        try:
            metrics = stats_metrics(
                stats=container.stats(stream=False),
                host_network=is_host_network(attrs=container.attrs),
            )
        except Exception as error:
            LOGGER.debug("Docker stats unavailable for %s: %s", container.id, error)
        with self._lock:
            self._cache[container.id] = (self._clock(), metrics)
            self._inflight.discard(container.id)
