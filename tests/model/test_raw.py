from dataclasses import replace

import pytest

from tests.helpers import invalid_model_value
from wimm.model import MemInfo, MetricsSource, Mount, RawContainer, RawProcess, RawSocket


@pytest.fixture
def process() -> RawProcess:
    return RawProcess(
        pid=42,
        ppid=1,
        uid=1000,
        name="python",
        exe="/usr/bin/python3",
        cmdline=("python", "app.py"),
        cwd=None,
        create_time=123.125,
        cpu_time_s=0.1,
        pss=10,
        uss=9,
        swap=2,
        rss=20,
        cgroup="/user.slice",
        terminal=None,
        tpgid=None,
        pgid=None,
    )


@pytest.fixture
def container() -> RawContainer:
    return RawContainer(
        id="c",
        name="db",
        image="postgres",
        state="running",
        labels=(("project", "demo"),),
        mounts=(Mount(type="volume", source="data", destination="/data"),),
        ports=(5432,),
        pid=43,
        memory_bytes=100,
        cpu_usage_usec=12,
        net_bytes=50,
        metrics_source=MetricsSource.CGROUP,
    )


@pytest.fixture
def meminfo() -> MemInfo:
    return MemInfo(
        mem_total=100,
        mem_free=10,
        mem_available=30,
        cached=20,
        buffers=5,
        s_reclaimable=4,
        shmem=2,
        swap_total=50,
        swap_free=40,
    )


def test_raw_collector_contracts_are_frozen_and_slotted(
    process: RawProcess, container: RawContainer, meminfo: MemInfo
) -> None:
    socket = RawSocket(pid=None, laddr=("127.0.0.1", 8000), raddr=None, status="LISTEN")
    assert (process.create_time, container.memory_bytes, meminfo.mem_total) == (123.125, 100, 100)
    assert socket.laddr == ("127.0.0.1", 8000)
    for instance in (process, container.mounts[0], container, meminfo, socket):
        assert not hasattr(instance, "__dict__")
        with pytest.raises(TypeError, match="super"):
            invalid_model_value(instance).extra = "mutation"


@pytest.mark.parametrize("field", ["pss", "uss", "swap", "rss"])
@pytest.mark.parametrize("value", [-1, 0.5, True])
def test_raw_process_byte_fields(process: RawProcess, field: str, value: object) -> None:
    assert getattr(process, field) >= 0
    with pytest.raises(ValueError, match=field):
        replace(process, **invalid_model_value({field: value}))


@pytest.mark.parametrize("field", ["memory_bytes", "net_bytes"])
def test_raw_container_byte_fields_and_nested_immutability(
    container: RawContainer, field: str
) -> None:
    assert container.memory_bytes == 100
    with pytest.raises(ValueError, match=field):
        replace(container, **invalid_model_value({field: 0.5}))
    with pytest.raises(ValueError, match=field):
        replace(container, **invalid_model_value({field: -1}))
    with pytest.raises(ValueError, match="labels"):
        replace(container, labels=invalid_model_value((("key", ["mutable"]),)))


@pytest.mark.parametrize(
    "field",
    [
        "mem_total",
        "mem_free",
        "mem_available",
        "cached",
        "buffers",
        "s_reclaimable",
        "shmem",
        "swap_total",
        "swap_free",
    ],
)
def test_meminfo_bytes(meminfo: MemInfo, field: str) -> None:
    assert getattr(meminfo, field) >= 0
    with pytest.raises(ValueError, match=field):
        replace(meminfo, **invalid_model_value({field: True}))


@pytest.mark.parametrize(
    "pgid,tpgid,expected",
    [(None, None, False), (1, None, False), (None, 1, False), (1, 2, False), (1, 1, True)],
)
def test_foreground_is_derived(
    process: RawProcess, pgid: int | None, tpgid: int | None, expected: bool
) -> None:
    assert replace(process, pgid=pgid, tpgid=tpgid).is_foreground is expected


def test_process_preserves_unavailable_fields(process: RawProcess) -> None:
    partial = replace(
        process,
        exe=None,
        cmdline=None,
        cwd=None,
        create_time=None,
        cpu_time_s=None,
        pss=None,
        uss=None,
        swap=None,
        terminal=None,
        tpgid=None,
        pgid=None,
    )
    identity = (42, 1, 1000, "python", 20, "/user.slice")
    fields = ("pid", "ppid", "uid", "name", "rss", "cgroup")
    assert tuple(getattr(partial, name) for name in fields) == identity
    assert (
        partial.exe,
        partial.cmdline,
        partial.create_time,
        partial.cpu_time_s,
        partial.pss,
        partial.uss,
        partial.swap,
        partial.terminal,
        partial.tpgid,
        partial.pgid,
    ) == (None,) * 10


@pytest.mark.parametrize("source", list(MetricsSource))
def test_container_records_metrics_source(container: RawContainer, source: MetricsSource) -> None:
    assert replace(container, metrics_source=source).metrics_source is source


@pytest.mark.parametrize("value", [-1, True, 0.5])
def test_container_rejects_invalid_cpu_counter(container: RawContainer, value: object) -> None:
    assert replace(container, cpu_usage_usec=0).cpu_usage_usec == 0
    with pytest.raises(ValueError, match="cpu_usage_usec"):
        replace(container, cpu_usage_usec=invalid_model_value(value))


@pytest.mark.parametrize("field", ["pid", "ppid"])
@pytest.mark.parametrize("value", [-1, True, 0.5])
def test_raw_process_rejects_invalid_pid(process: RawProcess, field: str, value: object) -> None:
    assert getattr(replace(process, **invalid_model_value({field: 0})), field) == 0
    with pytest.raises(ValueError, match=field):
        replace(process, **invalid_model_value({field: value}))


@pytest.mark.parametrize("value", [-1, True, 0.5])
def test_raw_container_and_socket_reject_invalid_pid(
    container: RawContainer, value: object
) -> None:
    assert replace(container, pid=0).pid == 0
    assert RawSocket(pid=0, laddr=None, raddr=None, status="NONE").pid == 0
    with pytest.raises(ValueError, match="pid"):
        replace(container, pid=invalid_model_value(value))
    with pytest.raises(ValueError, match="pid"):
        RawSocket(pid=invalid_model_value(value), laddr=None, raddr=None, status="NONE")


@pytest.mark.parametrize("value", [-1, 65536, True, 0.5])
def test_raw_container_and_socket_ports(container: RawContainer, value: object) -> None:
    assert replace(container, ports=(0, 65535)).ports == (0, 65535)
    with pytest.raises(ValueError, match="ports"):
        replace(container, ports=invalid_model_value((value,)))
    for field in ("laddr", "raddr"):
        socket = RawSocket(pid=None, laddr=("host", 0), raddr=("host", 65535), status="TCP")
        assert socket.raddr == ("host", 65535)
        with pytest.raises(ValueError, match=field):
            replace(socket, **invalid_model_value({field: ("host", value)}))


@pytest.mark.parametrize("field", ["pgid", "tpgid"])
@pytest.mark.parametrize("value", [-1, True, 0.5])
def test_raw_process_group_ids(process: RawProcess, field: str, value: object) -> None:
    assert getattr(replace(process, **invalid_model_value({field: 0})), field) == 0
    with pytest.raises(ValueError, match=field):
        replace(process, **invalid_model_value({field: value}))


def test_metrics_source_catalog() -> None:
    assert {source.name: source.value for source in MetricsSource} == {
        "CGROUP": "cgroup",
        "STATS_API": "stats_api",
        "UNAVAILABLE": "unavailable",
    }


def test_raw_process_requires_rss(process: RawProcess) -> None:
    assert replace(process, rss=0).rss == 0
    with pytest.raises(ValueError, match="rss"):
        replace(process, rss=invalid_model_value(None))


def test_raw_container_net_bytes_none_means_not_measured(container: RawContainer) -> None:
    assert replace(container, net_bytes=None).net_bytes is None
    assert replace(container, net_bytes=0).net_bytes == 0
