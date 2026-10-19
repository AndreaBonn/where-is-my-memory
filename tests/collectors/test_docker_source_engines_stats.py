import logging
import threading
import time
from pathlib import Path

import pytest

from tests.collectors.docker_source_engines_helpers import (
    DOCKER,
    PODMAN,
    FakeContainer,
    FakeEngineClient,
    FakeEngines,
    engine,
    source_of,
)
from wimm.collectors import docker_engines, docker_stats
from wimm.collectors.docker_source import DockerSource
from wimm.core.docker_endpoint import (
    DockerEndpoint,
    EndpointResolution,
    EndpointSource,
)
from wimm.core.docker_notices import NoticeCode
from wimm.model.actions import EngineIdentity
from wimm.model.enums import MetricsSource
from wimm.model.raw import RawContainer


def running(count: int) -> list[FakeContainer]:
    return [FakeContainer(f"c{index:02d}") for index in range(count)]


def test_stats_are_read_for_a_few_containers_per_cycle_and_rotate(tmp_path: Path) -> None:
    containers = running(10)
    client = FakeEngineClient(containers)
    source = source_of(FakeEngines([engine(DOCKER, client, "a")]), tmp_path)
    limit = docker_stats.STATS_MAX_PER_CYCLE

    first = source.collect().data.containers
    assert sum(item.metrics_source is MetricsSource.STATS_API for item in first) == limit
    assert sum(c.calls for c in containers) == limit

    second = source.collect().data.containers
    sampled = [item.id for item in second if item.metrics_source is MetricsSource.STATS_API]
    assert len(sampled) == 2 * limit
    assert all(c.calls <= 1 for c in containers)

    for _ in range(3):
        source.collect()
    final = source.collect().data.containers
    assert all(item.metrics_source is MetricsSource.STATS_API for item in final)
    assert all(c.calls == 1 for c in containers)


def test_a_container_without_a_reading_yet_is_unavailable_not_zero(tmp_path: Path) -> None:
    containers = running(docker_stats.STATS_MAX_PER_CYCLE + 1)
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient(containers), "a")]), tmp_path)
    waiting = [
        item
        for item in source.collect().data.containers
        if item.metrics_source is MetricsSource.UNAVAILABLE
    ]
    assert len(waiting) == 1
    assert (waiting[0].memory_bytes, waiting[0].net_bytes) == (0, None)


def test_a_slow_stats_call_does_not_hold_the_cycle_and_lands_in_the_next_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(target=docker_stats, name="STATS_BUDGET_S", value=0.05)
    slow = FakeContainer("slow")
    slow.gate = threading.Event()
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient([slow]), "a")]), tmp_path)

    started = time.monotonic()
    (first,) = source.collect().data.containers
    assert time.monotonic() - started < 2
    assert first.metrics_source is MetricsSource.UNAVAILABLE

    slow.gate.set()
    second = _collect_until_stats(source=source)
    assert second.metrics_source is MetricsSource.STATS_API
    assert second.memory_bytes == 70
    assert slow.calls == 1


def test_a_call_still_running_is_not_started_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(target=docker_stats, name="STATS_BUDGET_S", value=0.02)
    slow = FakeContainer("slow")
    slow.gate = threading.Event()
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient([slow]), "a")]), tmp_path)
    source.collect()
    source.collect()
    slow.gate.set()
    _collect_until_stats(source=source)
    assert slow.calls == 1


def test_cycle_duration_is_logged_at_debug(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = source_of(FakeEngines([engine(DOCKER, FakeEngineClient(running(2)), "a")]), tmp_path)
    with caplog.at_level(level=logging.DEBUG, logger="wimm.collectors.docker_source"):
        source.collect()
    (line,) = [r.getMessage() for r in caplog.records if "Docker sample" in r.getMessage()]
    assert "2 containers" in line and " s" in line


def _collect_until_stats(*, source: DockerSource, timeout_s: float = 5.0) -> RawContainer:
    """Collect until the background stats call has landed; a collect never starts a second one."""
    deadline = time.monotonic() + timeout_s
    while True:
        (item,) = source.collect().data.containers
        if item.metrics_source is MetricsSource.STATS_API:
            return item
        assert time.monotonic() < deadline, "stats call never landed"
        time.sleep(0.01)


class StallingClient(FakeEngineClient):
    """An engine whose socket exists but never answers: `info()` ends in the client timeout."""

    def __init__(self) -> None:
        super().__init__()
        self.info_calls = 0

    def info(self) -> dict[str, str]:
        self.info_calls += 1
        raise TimeoutError("timed out")


def test_a_stalling_engine_is_not_asked_again_during_backoff_and_does_not_hide_the_healthy_one(
    tmp_path: Path,
) -> None:
    stalling = StallingClient()
    healthy = FakeEngineClient([FakeContainer("d1", state="exited")])
    clients = {PODMAN: stalling, DOCKER: healthy}
    now = [1000.0]

    def resolve() -> EndpointResolution:
        return EndpointResolution(
            endpoints=tuple(
                DockerEndpoint(
                    source=EndpointSource.DEFAULT_SOCKET, url="unix://" + p, path=p, realpath=p
                )
                for p in (PODMAN, DOCKER)
            ),
            rejected=(),
        )

    pool = docker_engines.EnginePool(
        resolve=resolve,
        connect=lambda found: clients[found.path],
        identify=lambda path: EngineIdentity(path=path, st_ino=1, st_dev=1),
        clock=lambda: now[0],
    )
    source = DockerSource(roots=(tmp_path, tmp_path), engines=pool)

    first = source.collect()
    second = source.collect()
    assert stalling.info_calls == 1
    for result in (first, second):
        assert [item.id for item in result.data.containers] == ["d1"]
        (notice,) = result.data.notices
        assert (notice.code, notice.endpoint) == (NoticeCode.UNREACHABLE, PODMAN)

    now[0] += docker_engines.BACKOFF_INITIAL_S
    source.collect()
    assert stalling.info_calls == 2
