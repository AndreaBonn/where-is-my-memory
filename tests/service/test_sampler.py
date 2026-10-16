from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.core.helpers import meminfo, process
from wimm.collectors import CollectorResult
from wimm.collectors.docker_source import DockerSample
from wimm.config import Config
from wimm.model.memory import DiskUsage
from wimm.model.raw import RawSocket
from wimm.model.snapshot import DockerStatus, ProcessMember
from wimm.paths import UserPaths
from wimm.service.sampler import Collectors, Sampler, SamplerEnvironment

NOW = datetime(2026, 10, 16, tzinfo=UTC)
DISK = DiskUsage(mount="/", total=1000, used=600, free=400)


def make_sampler(tmp_path: Path) -> Sampler:
    collectors = Collectors(
        processes=lambda: CollectorResult(data=()),
        sockets=lambda: CollectorResult(data=()),
        docker=lambda: CollectorResult(
            data=DockerSample(status=DockerStatus(available=True, error=None), containers=())
        ),
        meminfo=lambda: CollectorResult(data=meminfo()),
        disks=lambda: CollectorResult(data=(DISK,)),
        desktop=lambda: CollectorResult(data={}),
    )
    environment = SamplerEnvironment(
        paths=UserPaths(config_dir=tmp_path, state_dir=tmp_path, cache_dir=tmp_path),
        own_pid=999,
        uid=1000,
        home=tmp_path,
    )
    return Sampler(
        collectors=collectors, environment=environment, config=Config(), clock=lambda: NOW
    )


def test_sampler_assembles_and_survives_docker_error(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=10)
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(data=(proc,)),
        docker=lambda: CollectorResult(
            data=DockerSample(status=DockerStatus(available=True, error=None), containers=()),
            error="offline",
        ),
    )
    snapshot = sampler.run_cycle()
    member = snapshot.groups[0].members[0]
    assert isinstance(member, ProcessMember)
    assert member.pid == 20
    assert snapshot.docker == DockerStatus(available=False, error="offline")
    assert snapshot.monitor_started_at == NOW


def test_sampler_cpu_uses_surviving_identities_and_descendant_ports(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    parent = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=10)
    child = process(pid=21, ppid=20, create_time=2, cpu_time_s=100)
    records = [parent, child]
    sockets = (
        RawSocket(pid=21, laddr=("127.0.0.1", 8000), raddr=None, status="LISTEN"),
        RawSocket(
            pid=None, laddr=("127.0.0.1", 8000), raddr=("127.0.0.1", 50000), status="ESTABLISHED"
        ),
    )
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(data=tuple(records)),
        sockets=lambda: CollectorResult(data=sockets),
    )
    sampler.run_cycle()
    records[:] = [replace(parent, cpu_time_s=12), replace(child, create_time=3, cpu_time_s=900)]
    sampler.clock = lambda: NOW + timedelta(seconds=30)
    sampler.run_cycle()
    samples = sampler.history.history_for(key=(20, 1.0))
    assert samples[0].cpu_time_s == 0
    assert samples[-1].cpu_time_s == 2
    assert samples[-1].connections == frozenset({("127.0.0.1", 8000, "127.0.0.1", 50000)})
    records[:] = [replace(parent, cpu_time_s=15)]
    sampler.clock = lambda: NOW + timedelta(seconds=60)
    sampler.run_cycle()
    assert sampler.history.history_for(key=(20, 1.0))[-1].cpu_time_s == 5


def test_sampler_missing_sockets_are_unknown_and_exception_recovers(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=0)
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(data=(proc,)),
        sockets=lambda: CollectorResult(data=(), error="denied"),
    )
    sampler.run_cycle()
    assert sampler.history.history_for(key=(20, 1.0))[-1].connections is None

    def broken() -> CollectorResult[tuple[()]]:
        raise RuntimeError("collector exploded")

    original = sampler.collectors
    sampler.collectors = replace(original, processes=broken)
    with pytest.raises(RuntimeError, match="collector exploded"):
        sampler.run_cycle()
    sampler.collectors = original
    member = sampler.run_cycle().groups[0].members[0]
    assert isinstance(member, ProcessMember)
    assert member.pid == 20


def test_sampler_retains_last_valid_system_counters(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    first = sampler.run_cycle()
    sampler.collectors = replace(
        sampler.collectors,
        meminfo=lambda: CollectorResult(data=None, error="unreadable"),
        disks=lambda: CollectorResult(data=(), error="unreadable"),
    )
    assert sampler.run_cycle().memory == first.memory
    assert sampler.run_cycle().disk == DISK


def test_sampler_without_system_counters_fails_then_recovers(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    original = sampler.collectors
    sampler.collectors = replace(
        original, meminfo=lambda: CollectorResult(data=None, error="denied")
    )
    with pytest.raises(RuntimeError, match="not ready"):
        sampler.run_cycle()
    sampler.collectors = original
    assert sampler.run_cycle().disk == DISK


def test_sampler_new_project_markers_are_seen_next_cycle(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    root = tmp_path / "project"
    cwd = root / "app"
    cwd.mkdir(parents=True)
    proc = process(name="node", cmdline=("node",), cwd=str(cwd), create_time=1, cpu_time_s=0)
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(proc,))
    )
    first = sampler.run_cycle()
    (root / "pyproject.toml").touch()
    second = sampler.run_cycle()
    assert first.groups[0].id != second.groups[0].id
    assert second.monitor_started_at == first.monitor_started_at


def test_sampler_container_cpu_and_network_are_recorded(tmp_path: Path) -> None:
    from tests.core.assemble_helpers import container
    from wimm.model.enums import MetricsSource

    sampler = make_sampler(tmp_path=tmp_path)
    item = replace(container("demo"), cpu_usage_usec=2_500_000, net_bytes=300)
    sampler.collectors = replace(
        sampler.collectors,
        docker=lambda: CollectorResult(
            data=DockerSample(
                status=DockerStatus(available=True, error=None),
                containers=(item,),
            )
        ),
    )
    assert sampler.run_cycle().groups[0].members[0].name == "demo"
    assert sampler.history.history_for(key=item.id)[0].cpu_time_s == 2.5
    assert sampler.history.history_for(key=item.id)[0].net_bytes == 300
    item = replace(item, metrics_source=MetricsSource.UNAVAILABLE)
    sampler.run_cycle()
    assert sampler.history.history_for(key=item.id)[-1].cpu_time_s is None


def test_sampler_excludes_children_without_verified_identity(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    parent = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=10)
    child = process(pid=21, ppid=20, create_time=None, cpu_time_s=100)
    records = [parent, child]
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=tuple(records))
    )
    sampler.run_cycle()
    records[:] = [replace(parent, cpu_time_s=12), replace(child, cpu_time_s=900)]
    sampler.clock = lambda: NOW + timedelta(seconds=30)
    sampler.run_cycle()
    assert sampler.history.history_for(key=(20, 1.0))[-1].cpu_time_s == 2


def test_sampler_adds_cpu_deltas_of_both_parent_and_live_child(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    parent = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=10)
    child = process(pid=21, ppid=20, create_time=2, cpu_time_s=100)
    records = [parent, child]
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=tuple(records))
    )
    sampler.run_cycle()
    records[:] = [replace(parent, cpu_time_s=12), replace(child, cpu_time_s=103)]
    sampler.clock = lambda: NOW + timedelta(seconds=30)
    sampler.run_cycle()
    assert sampler.history.history_for(key=(20, 1.0))[-1].cpu_time_s == 5
    assert sampler.history.history_for(key=(21, 2.0))[-1].cpu_time_s == 3


def test_empty_process_error_preserves_cpu_and_history(tmp_path: Path) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1, cpu_time_s=10)
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(proc,))
    )
    sampler.run_cycle()
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(), error="denied")
    )
    with pytest.raises(RuntimeError, match="denied"):
        sampler.run_cycle()
    assert len(sampler.history.history_for(key=(20, 1.0))) == 1
    proc = replace(proc, cpu_time_s=15)
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(proc,))
    )
    sampler.run_cycle()
    assert sampler.history.history_for(key=(20, 1.0))[-1].cpu_time_s == 5


def test_partial_process_error_keeps_data_and_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1)
    sampler.collectors = replace(
        sampler.collectors, processes=lambda: CollectorResult(data=(proc,), error="partial")
    )
    for _ in range(2):
        member = sampler.run_cycle().groups[0].members[0]
        assert isinstance(member, ProcessMember)
        assert member.pid == 20
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


@pytest.mark.parametrize("reused", [False, True])
def test_socket_failure_keeps_ports_only_for_same_identity(tmp_path: Path, reused: bool) -> None:
    sampler = make_sampler(tmp_path=tmp_path)
    proc = process(pid=20, name="node", cmdline=("node",), create_time=1)
    sampler.collectors = replace(
        sampler.collectors,
        processes=lambda: CollectorResult(data=(proc,)),
        sockets=lambda: CollectorResult(
            data=(RawSocket(pid=20, laddr=("127.0.0.1", 8000), raddr=None, status="LISTEN"),)
        ),
    )
    first = sampler.run_cycle()
    create_time = 2.0 if reused else 1.0
    proc = replace(proc, create_time=create_time)
    sampler.collectors = replace(
        sampler.collectors, sockets=lambda: CollectorResult(data=(), error="denied")
    )
    second = sampler.run_cycle()
    assert sampler.history.history_for(key=(20, create_time))[-1].connections is None
    if reused:
        assert second.groups[0].category != first.groups[0].category
    else:
        assert second.groups[0].category == first.groups[0].category
