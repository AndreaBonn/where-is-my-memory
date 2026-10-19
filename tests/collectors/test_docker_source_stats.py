import logging
from pathlib import Path

import docker.errors
import pytest

from tests.collectors.docker_source_helpers import FakeContainer, FakeReader, _docker_memory_rows
from wimm.collectors import docker_source
from wimm.collectors.docker_engines import Engine, EngineView, FixedEngines
from wimm.collectors.docker_source import (
    DOCKER_TIMEOUT_S,
    DockerSource,
)
from wimm.collectors.docker_stats import STATS_MAX_PER_CYCLE, stats_metrics
from wimm.model.enums import MetricsSource


def test_stats_fallback_starts_a_bounded_batch_per_cycle_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    barrier = threading.Barrier(parties=STATS_MAX_PER_CYCLE, timeout=3)
    threads: set[int] = set()
    containers = [FakeContainer() for _ in range(STATS_MAX_PER_CYCLE * 2)]
    for index, container in enumerate(containers):
        container.id = str(index)
    original = FakeContainer.stats

    def read(self: FakeContainer, stream: bool) -> dict[str, object]:
        threads.add(threading.get_ident())
        barrier.wait()
        return original(self=self, stream=stream)

    monkeypatch.setattr(target=FakeContainer, name="stats", value=read)
    result = DockerSource(
        reader=FakeReader(containers=containers), roots=(tmp_path, tmp_path)
    ).collect()
    sources = [item.metrics_source for item in result.data.containers]
    assert len(sources) == len(containers)
    assert sources.count(MetricsSource.STATS_API) == STATS_MAX_PER_CYCLE
    assert sources.count(MetricsSource.UNAVAILABLE) == len(containers) - STATS_MAX_PER_CYCLE
    assert len(threads) == STATS_MAX_PER_CYCLE


def test_default_engines_are_created_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def create(timeout: int) -> FixedEngines:
        calls.append(timeout)
        return FixedEngines(client=FakeReader())

    monkeypatch.setattr(target=docker_source, name="local_pool", value=create)
    source = DockerSource()
    assert calls == []
    assert source.collect().data.status.available
    assert source.collect().data.status.available
    assert calls == [DOCKER_TIMEOUT_S]


def test_docker_cli_memory_parser() -> None:
    # 1.5 MiB = 1.5 * 1024 * 1024 bytes, 2 kB = 2000 bytes, "B" rows stay as they are.
    output = "abc 1.5MiB / 4GiB\ndef 32B / 4GiB\nghi 2kB / 4GiB"
    assert _docker_memory_rows(output=output) == {"abc": 1572864.0, "def": 32.0, "ghi": 2000.0}


def _write_cgroup(root: Path, current: int, inactive: int) -> None:
    scope = root / "system.slice/docker-abc.scope"
    scope.mkdir(parents=True, exist_ok=True)
    (scope / "memory.current").write_text(str(current))
    (scope / "memory.stat").write_text(f"anon 1\ninactive_file {inactive}\nfile 5")
    (scope / "cpu.stat").write_text("usage_usec 9")
    net = root / "42/net"
    net.mkdir(parents=True, exist_ok=True)
    (net / "dev").write_text("eth0: 10 0 0 0 0 0 0 0 20")


@pytest.mark.parametrize(("current", "inactive", "expected"), [(1000, 300, 700), (100, 300, 0)])
def test_memory_is_current_minus_inactive_file_clamped(
    tmp_path: Path, current: int, inactive: int, expected: int
) -> None:
    _write_cgroup(root=tmp_path, current=current, inactive=inactive)
    source = DockerSource(reader=FakeReader(containers=[FakeContainer()]), roots=(tmp_path,) * 2)
    (item,) = source.collect().data.containers
    assert item.memory_bytes == expected


def test_malformed_mount_and_port_skip_only_the_field(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = FakeContainer()
    broken.attrs["Mounts"] = [
        {"Type": "bind", "Source": "/s"},
        {"Type": "bind", "Source": "/s", "Destination": "/d"},
    ]
    broken.attrs["NetworkSettings"] = {
        "Ports": {"80/tcp": [{"HostPort": "x"}], "81/tcp": [{"HostPort": "81"}]}
    }
    other = FakeContainer()
    other.id = "other"
    source = DockerSource(reader=FakeReader(containers=[broken, other]), roots=(tmp_path,) * 2)
    with caplog.at_level(level=logging.WARNING):
        result = source.collect()
    assert result.data.status.available
    first = result.data.containers[0]
    assert [mount.destination for mount in first.mounts] == ["/d"]
    assert first.ports == (81,)
    assert len(result.data.containers) == 2
    assert "abc" in caplog.text


def test_failing_container_is_skipped_not_the_sample(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = FakeContainer()
    broken.attrs["State"] = {"Status": "exited", "Pid": "not-a-number"}
    good = FakeContainer(state="exited")
    good.id = "good"
    source = DockerSource(reader=FakeReader(containers=[broken, good]), roots=(tmp_path,) * 2)
    with caplog.at_level(level=logging.WARNING):
        result = source.collect()
    assert result.data.status.available
    assert [item.id for item in result.data.containers] == ["good"]
    assert "abc" in caplog.text


def test_host_network_has_no_net_bytes(tmp_path: Path) -> None:
    _write_cgroup(root=tmp_path, current=100, inactive=30)
    container = FakeContainer()
    container.attrs["HostConfig"] = {"NetworkMode": "host"}
    source = DockerSource(reader=FakeReader(containers=[container]), roots=(tmp_path,) * 2)
    (item,) = source.collect().data.containers
    assert (item.metrics_source, item.memory_bytes, item.net_bytes) == (
        MetricsSource.CGROUP,
        70,
        None,
    )


def test_host_network_stats_fallback_has_no_net_bytes(tmp_path: Path) -> None:
    container = FakeContainer()
    container.attrs["HostConfig"] = {"NetworkMode": "host"}
    source = DockerSource(reader=FakeReader(containers=[container]), roots=(tmp_path,) * 2)
    (item,) = source.collect().data.containers
    assert (item.metrics_source, item.net_bytes) == (MetricsSource.STATS_API, None)


def test_running_with_zero_pid_skips_cgroup_reads(tmp_path: Path) -> None:
    _write_cgroup(root=tmp_path, current=100, inactive=30)
    container = FakeContainer()
    container.state["Pid"] = 0
    source = DockerSource(reader=FakeReader(containers=[container]), roots=(tmp_path,) * 2)
    (item,) = source.collect().data.containers
    assert item.metrics_source is MetricsSource.STATS_API
    assert container.calls == 1


class FlakyEngines:
    """A provider whose first refresh fails, like a pool that cannot resolve its endpoints."""

    def __init__(self) -> None:
        self.attempts = 0
        self._fixed = FixedEngines(client=FakeReader())

    def refresh(self) -> EngineView:
        self.attempts += 1
        if self.attempts == 1:
            raise docker.errors.DockerException("socket missing")
        return self._fixed.refresh()

    def discard(self, *, engine: Engine) -> None:
        self._fixed.discard(engine=engine)


def test_a_failing_refresh_is_unavailable_then_retried() -> None:
    engines = FlakyEngines()
    source = DockerSource(engines=engines)
    first = source.collect()
    assert (first.data.status.available, first.data.status.error) == (False, "socket missing")
    assert source.collect().data.status.available
    assert engines.attempts == 2


def test_stats_memory_below_the_inactive_page_cache_is_clamped_to_zero() -> None:
    stats = {"memory_stats": {"usage": 20, "stats": {"inactive_file": 30}}}

    memory, _cpu, _network = stats_metrics(stats=stats, host_network=True)

    assert memory == 0
    assert stats_metrics(stats={"memory_stats": {"usage": 50}}, host_network=True)[0] == 50


def test_container_whose_metadata_cannot_be_read_after_the_stats_phase_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = FakeContainer()
    broken.attrs["Config"] = {"Image": "image:tag", "Labels": 5}  # no cgroup: goes to the stats API
    good = FakeContainer()
    good.id = "good"
    source = DockerSource(reader=FakeReader(containers=[broken, good]), roots=(tmp_path,) * 2)

    with caplog.at_level(level=logging.WARNING):
        result = source.collect()

    assert result.data.status.available
    assert [item.id for item in result.data.containers] == ["good"]
    assert [item.metrics_source for item in result.data.containers] == [MetricsSource.STATS_API]
    assert "Skipping container abc" in caplog.text
