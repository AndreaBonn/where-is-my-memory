import logging
import os
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import psutil
import pytest

from wimm.collectors.cgroups import collect_process_cgroup, is_docker_scope
from wimm.collectors.processes import collect_processes

# RNF-03: a full sampling cycle stays under 1.5 s with ~900 processes.
SCAN_CPU_BUDGET_S = 1.5


class FakeProcess:
    def __init__(self, pid: int, uid: int, failure: str = "") -> None:
        self.pid = pid
        self.failure = failure
        self.info = {
            "pid": pid,
            "name": "worker",
            "uids": SimpleNamespace(real=uid),
            "memory_info": SimpleNamespace(rss=100),
        }
        self.calls: list[str] = []

    def __getattr__(self, field: str) -> Callable[[], object]:
        def read() -> object:
            self.calls.append(field)
            if field == self.failure:
                raise psutil.AccessDenied(pid=self.pid)
            return {
                "exe": "/bin/worker",
                "cmdline": ["worker", "arg"],
                "cwd": "/work",
                "create_time": 10.0,
                "ppid": 1,
                "terminal": None,
                "cpu_times": SimpleNamespace(user=2.0, system=3.0),
                "memory_full_info": SimpleNamespace(pss=50, uss=30, swap=5, rss=100),
            }[field]

        return read


class FakeSource:
    def __init__(self, processes: Sequence[FakeProcess]) -> None:
        self.processes = processes
        self.attrs: list[str] | None = None

    def process_iter(self, attrs: list[str]) -> Iterator[psutil.Process]:
        self.attrs = attrs
        return (cast(psutil.Process, item) for item in self.processes)


def proc_files(root: Path, pid: int, docker: bool = False) -> None:
    directory = root / str(pid)
    directory.mkdir()
    group = "/system.slice/docker-abc.scope" if docker else "/user.slice/test.scope"
    (directory / "cgroup").write_text(f"0::{group}")
    (directory / "stat").write_text(f"{pid} (worker) S 1 22 30 34816 22")


def test_own_process_fields_and_denied_field(tmp_path: Path) -> None:
    proc_files(root=tmp_path, pid=42)
    source = FakeSource(processes=[FakeProcess(pid=42, uid=10, failure="cwd")])
    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)
    (process,) = result.data
    assert (process.pss, process.uss, process.swap, process.rss) == (50, 30, 5, 100)
    assert (process.cpu_time_s, process.pgid, process.tpgid) == (5, 22, 22)
    assert process.cmdline == ("worker", "arg")
    assert process.cwd is None
    assert process.exe == "/bin/worker"
    assert source.attrs == ["pid", "name", "uids", "memory_info"]


def test_docker_process_excluded_before_expensive_reads(tmp_path: Path) -> None:
    proc_files(root=tmp_path, pid=42, docker=True)
    proc_files(root=tmp_path, pid=43)
    excluded = FakeProcess(pid=42, uid=10)
    source = FakeSource(processes=[excluded, FakeProcess(pid=43, uid=10)])
    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)
    assert [process.pid for process in result.data] == [43]
    assert excluded.calls == []


def test_denied_memory_preserves_rss(tmp_path: Path) -> None:
    proc_files(root=tmp_path, pid=42)
    source = FakeSource(processes=[FakeProcess(pid=42, uid=10, failure="memory_full_info")])
    (process,) = collect_processes(source=source, own_uid=10, proc_root=tmp_path).data
    assert (process.pss, process.uss, process.swap, process.rss) == (None, None, None, 100)


@pytest.mark.integration
# CPU time also inflates under contention (1.62 s at load 26 on 16 cores, 918 processes):
# like the other budgets it runs on a quiet machine with make perf (decision 2026-10-19).
@pytest.mark.perf
def test_real_user_process_scan_under_budget(caplog: pytest.LogCaptureFixture) -> None:
    own_cgroup = collect_process_cgroup(pid=os.getpid()).data
    if own_cgroup is not None and is_docker_scope(path=own_cgroup):
        pytest.skip(reason="Test process runs in a docker scope, excluded from the census")
    # CPU time, not wall clock: RNF-03 bounds the cost of a cycle, and wall time on a
    # loaded machine also counts scheduler waits (1.7 s wall for 0.73 s of work, measured).
    start = time.process_time()
    with caplog.at_level(level=logging.DEBUG):
        result = collect_processes()
    elapsed = time.process_time() - start
    assert any(process.pid == os.getpid() for process in result.data)
    assert elapsed < SCAN_CPU_BUDGET_S
    logging.getLogger(__name__).warning(
        "VERIFY processes: %.3f ms, %d records", elapsed * 1000, len(result.data)
    )


@pytest.mark.parametrize("failure", [psutil.NoSuchProcess, psutil.ZombieProcess])
def test_gone_process_does_not_discard_other_records(
    tmp_path: Path, failure: type[psutil.NoSuchProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_files(root=tmp_path, pid=42)
    proc_files(root=tmp_path, pid=43)
    gone = FakeProcess(pid=42, uid=10)

    def fail() -> object:
        raise failure(pid=42)

    monkeypatch.setattr(target=gone, name="cwd", value=fail)
    source = FakeSource(processes=[gone, FakeProcess(pid=43, uid=10)])
    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)
    assert [process.pid for process in result.data] == [43]
    assert result.error is None


@pytest.mark.parametrize("field", ["exe", "cmdline", "create_time", "cpu_times", "terminal"])
def test_access_denied_preserves_other_fields(tmp_path: Path, field: str) -> None:
    proc_files(root=tmp_path, pid=42)
    source = FakeSource(processes=[FakeProcess(pid=42, uid=10, failure=field)])
    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)
    (process,) = result.data
    attribute = "cpu_time_s" if field == "cpu_times" else field
    assert getattr(process, attribute) is None
    assert process.pss == 50
    assert process.cwd == "/work"


@pytest.mark.parametrize("field", ["ppid", "cgroup", "rss"])
def test_required_missing_field_skips_process(tmp_path: Path, field: str) -> None:
    proc_files(root=tmp_path, pid=42)
    process = FakeProcess(pid=42, uid=10, failure="ppid" if field == "ppid" else "memory_full_info")
    if field == "cgroup":
        (tmp_path / "42/cgroup").unlink()
    if field == "rss":
        process.info["memory_info"] = None
    result = collect_processes(
        source=FakeSource(processes=[process]), own_uid=10, proc_root=tmp_path
    )
    assert result.data == ()
    assert result.error is None


def test_enumeration_failure_returns_readable_error(tmp_path: Path) -> None:
    class FailingSource:
        def process_iter(self, attrs: list[str]) -> Iterator[psutil.Process]:
            raise PermissionError("proc unavailable")

    result = collect_processes(source=FailingSource(), own_uid=10, proc_root=tmp_path)
    assert result.data == ()
    assert result.error == "proc unavailable"


def test_other_uid_process_has_six_fields_and_none_elsewhere(tmp_path: Path) -> None:
    proc_files(root=tmp_path, pid=7)
    other = FakeProcess(pid=7, uid=0)
    (process,) = collect_processes(
        source=FakeSource(processes=[other]), own_uid=10, proc_root=tmp_path
    ).data
    assert (process.pid, process.ppid, process.uid, process.name, process.rss) == (
        7,
        1,
        0,
        "worker",
        100,
    )
    assert process.cgroup == "/user.slice/test.scope"
    assert (process.exe, process.cmdline, process.cwd, process.create_time) == (None,) * 4
    assert (process.cpu_time_s, process.pss, process.uss, process.swap) == (None,) * 4
    assert (process.terminal, process.pgid, process.tpgid) == (None,) * 3
    assert "memory_full_info" not in other.calls


def test_failing_other_uid_read_skips_only_that_pid(tmp_path: Path) -> None:
    proc_files(root=tmp_path, pid=7)
    proc_files(root=tmp_path, pid=8)
    source = FakeSource(
        processes=[FakeProcess(pid=7, uid=0, failure="ppid"), FakeProcess(pid=8, uid=0)]
    )
    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)
    assert [process.pid for process in result.data] == [8]
    assert result.error is None


def test_unexpected_per_process_error_is_logged_at_debug(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    proc_files(root=tmp_path, pid=42)
    proc_files(root=tmp_path, pid=43)

    class Broken(FakeProcess):
        def memory_full_info(self) -> object:
            raise RuntimeError("boom")

    broken = Broken(pid=42, uid=10)
    source = FakeSource(processes=[broken, FakeProcess(pid=43, uid=10)])
    with caplog.at_level(level=logging.DEBUG):
        result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)
    assert [process.pid for process in result.data] == [43]
    # Positive pair of the negative below: the command line was read, it just is not logged.
    assert result.data[0].cmdline == ("worker", "arg")
    records = [r for r in caplog.records if "pid 42" in r.getMessage() and r.exc_info]
    assert records and records[0].levelno == logging.DEBUG
    assert "worker arg" not in caplog.text


def test_other_uid_process_without_a_readable_cgroup_is_skipped_alone(tmp_path: Path) -> None:
    proc_files(root=tmp_path, pid=8)  # pid 7 has no /proc entry at all
    source = FakeSource(processes=[FakeProcess(pid=7, uid=0), FakeProcess(pid=8, uid=0)])

    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)

    assert [process.pid for process in result.data] == [8]
    assert result.error is None


@pytest.mark.parametrize("missing", ["uids", "name"])
def test_process_whose_uid_or_name_cannot_be_read_is_skipped_alone(
    tmp_path: Path, missing: str
) -> None:
    proc_files(root=tmp_path, pid=7)
    proc_files(root=tmp_path, pid=8)
    unreadable = FakeProcess(pid=7, uid=10)
    unreadable.info[missing] = None
    source = FakeSource(processes=[unreadable, FakeProcess(pid=8, uid=10)])

    result = collect_processes(source=source, own_uid=10, proc_root=tmp_path)

    assert [process.pid for process in result.data] == [8]
    assert result.error is None
