import logging
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import docker.errors
import pytest

from wimm.collectors import docker_source
from wimm.collectors.docker_engines import Engine, EngineView, FixedEngines
from wimm.collectors.docker_source import (
    DOCKER_TIMEOUT_S,
    ContainerReader,
    DockerSource,
)
from wimm.collectors.docker_stats import STATS_MAX_PER_CYCLE, stats_metrics
from wimm.model.enums import MetricsSource
from wimm.model.raw import RawContainer


class FakeContainer:
    def __init__(self, state: str = "running") -> None:
        self.id = "abc"
        self.state = {"Status": state, "Pid": 42}
        self.attrs: dict[str, object] = {
            "Name": "/example",
            "Config": {"Image": "image:tag", "Labels": {"project": "demo"}},
            "State": self.state,
            "Mounts": [{"Type": "bind", "Source": "/source", "Destination": "/app"}],
            "NetworkSettings": {"Ports": {"80/tcp": [{"HostPort": "8080"}]}},
        }
        self.calls = 0
        self.failure = False

    def stats(self, stream: bool) -> dict[str, object]:
        assert stream is False
        self.calls += 1
        if self.failure:
            raise docker.errors.DockerException("stats failed")
        return {
            "memory_stats": {"usage": 100, "stats": {"inactive_file": 30}},
            "cpu_stats": {"cpu_usage": {"total_usage": 9000}},
            "networks": {
                "eth0": {"rx_bytes": 10, "tx_bytes": 20},
                "lo": {"rx_bytes": 999, "tx_bytes": 999},
            },
        }


class FakeReader:
    def __init__(self, containers: Sequence[FakeContainer] = ()) -> None:
        self.items = list(containers)
        self.containers = self
        self.failure = False

    def list(self, all: bool) -> Sequence[ContainerReader]:
        assert all is True
        if self.failure:
            raise docker.errors.DockerException("socket denied")
        return [cast(ContainerReader, item) for item in self.items]


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


MEMORY_TOLERANCE = 0.05
# Cache moves during the docker samples are absolute (8 MiB measured), not proportional:
# on a small total the relative tolerance alone is tighter than that noise.
MEMORY_NOISE_FLOOR = 8 * 1024 * 1024


def _running_containers() -> tuple[DockerSource, list[RawContainer]]:
    source = DockerSource()
    result = source.collect()
    if not result.data.status.available:
        pytest.skip(reason=f"Docker inaccessible: {result.error}")
    running = [item for item in result.data.containers if item.state == "running"]
    if not running:
        pytest.skip(reason="No running containers to compare")
    return source, running


@pytest.mark.integration
def test_real_docker_availability(caplog: pytest.LogCaptureFixture) -> None:
    result = DockerSource().collect()
    if result.data.status.available:
        assert result.data.status.error is None
        assert result.error is None
    else:
        assert result.data.containers == ()
        assert result.error and result.error == result.data.status.error
    logging.getLogger(__name__).warning(
        "VERIFY Docker available=%s, error=%s", result.data.status.available, result.error
    )


@pytest.mark.integration
def test_real_running_containers_are_read_from_cgroup_files() -> None:
    # The formula itself is pinned exactly by the fake-cgroup unit test above; a second live
    # read cannot pin it, because a cache-heavy container moves by MiB between two reads.
    # What only the real system can show is that every running container's cgroup resolves.
    _, running = _running_containers()
    assert all(item.metrics_source is MetricsSource.CGROUP for item in running)


@pytest.mark.integration
def test_real_total_container_memory_matches_docker_stats() -> None:
    # DoD 3 compares with docker stats. Per container, page cache moves between the active
    # and inactive lists during the ~2 s docker samples (8 MiB measured on a cache-heavy
    # container), so the comparison is on the total, where those moves are small.
    source, running = _running_containers()
    if not Path("/usr/bin/docker").is_file():
        pytest.skip(reason="Docker CLI is not installed")
    output = subprocess.run(
        args=["/usr/bin/docker", "stats", "--no-stream", "--format", "{{.ID}} {{.MemUsage}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    expected = _docker_memory_rows(output=output.stdout)
    after = {item.id: item for item in source.collect().data.containers}
    ours = docker = 0.0
    for item in running:
        identifier = next((key for key in expected if item.id.startswith(key)), None)
        later = after.get(item.id)
        if identifier is None or later is None:
            continue  # container started or stopped between reads
        ours += (item.memory_bytes + later.memory_bytes) / 2
        docker += expected[identifier]
    assert docker > 0
    assert abs(ours - docker) <= max(MEMORY_TOLERANCE * docker, MEMORY_NOISE_FLOOR)


def _docker_memory_rows(output: str) -> dict[str, float]:
    units = {
        "B": 1,
        "kB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
    }
    expected: dict[str, float] = {}
    for line in output.splitlines():
        identifier, memory, *_ = line.split()
        match = re.fullmatch(pattern=r"([\d.]+)([A-Za-z]+)", string=memory)
        assert match is not None
        expected[identifier] = float(match[1]) * units[match[2]]
    return expected


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
