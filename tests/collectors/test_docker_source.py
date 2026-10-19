import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.collectors.docker_source_helpers import FakeContainer, FakeReader
from wimm.collectors.docker_source import (
    DockerSource,
)
from wimm.model.enums import MetricsSource


def test_unavailable_warns_once_per_transition(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    reader = FakeReader()
    reader.failure = True
    source = DockerSource(reader=reader, roots=(tmp_path, tmp_path))
    first = source.collect()
    assert first.data.status.available is False
    assert first.data.status.error is not None
    assert "socket denied" in first.data.status.error
    assert first.data.containers == ()
    source.collect()
    assert len([record for record in caplog.records if record.levelno == logging.WARNING]) == 1
    reader.failure = False
    assert source.collect().data.status.available
    reader.failure = True
    source.collect()
    assert len([record for record in caplog.records if record.levelno == logging.WARNING]) == 2


def test_stats_fallback_rate_limit_and_metadata(tmp_path: Path) -> None:
    container = FakeContainer()
    clock = SimpleNamespace(now=0.0)
    source = DockerSource(
        reader=FakeReader(containers=[container]),
        roots=(tmp_path, tmp_path),
        clock=lambda: clock.now,
    )
    (item,) = source.collect().data.containers
    assert item.metrics_source is MetricsSource.STATS_API
    assert (item.memory_bytes, item.cpu_usage_usec, item.net_bytes) == (70, 9, 30)
    assert (item.name, item.image, item.labels, item.ports) == (
        "example",
        "image:tag",
        (("project", "demo"),),
        (8080,),
    )
    assert item.mounts[0].destination == "/app"
    clock.now = 299.9
    assert source.collect().data.containers == (item,)
    assert container.calls == 1
    clock.now = 300.0
    source.collect()
    assert container.calls == 2


def test_stopped_and_failed_stats_are_unavailable(tmp_path: Path) -> None:
    stopped = FakeContainer(state="exited")
    source = DockerSource(reader=FakeReader(containers=[stopped]), roots=(tmp_path, tmp_path))
    (item,) = source.collect().data.containers
    assert item.metrics_source is MetricsSource.UNAVAILABLE
    assert stopped.calls == 0
    stopped.state["Status"] = "running"
    stopped.failure = True
    assert source.collect().data.containers[0].metrics_source is MetricsSource.UNAVAILABLE
    source.collect()
    assert stopped.calls == 1


def test_container_that_stopped_and_restarted_gets_a_fresh_stats_read(tmp_path: Path) -> None:
    container = FakeContainer()
    clock = SimpleNamespace(now=0.0)
    source = DockerSource(
        reader=FakeReader(containers=[container]),
        roots=(tmp_path, tmp_path),
        clock=lambda: clock.now,
    )
    source.collect()
    assert container.calls == 1
    container.state["Status"] = "exited"
    clock.now = 10.0
    source.collect()
    container.state["Status"] = "running"
    clock.now = 20.0

    source.collect()

    assert container.calls == 2


def test_cgroup_normal_cycle_never_calls_stats(tmp_path: Path) -> None:
    container = FakeContainer()
    scope = tmp_path / "system.slice/docker-abc.scope"
    scope.mkdir(parents=True)
    (scope / "memory.current").write_text("100")
    (scope / "memory.stat").write_text("inactive_file 30")
    (scope / "cpu.stat").write_text("usage_usec 9")
    net = tmp_path / "42/net"
    net.mkdir(parents=True)
    (net / "dev").write_text("eth0: 10 0 0 0 0 0 0 0 20")
    source = DockerSource(reader=FakeReader(containers=[container]), roots=(tmp_path, tmp_path))
    (item,) = source.collect().data.containers
    assert item.metrics_source is MetricsSource.CGROUP
    assert (item.memory_bytes, item.cpu_usage_usec, item.net_bytes) == (70, 9, 30)
    assert container.calls == 0
