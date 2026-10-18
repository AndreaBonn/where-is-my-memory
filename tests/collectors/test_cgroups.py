import logging
from pathlib import Path

import pytest

from wimm.collectors.cgroups import (
    collect_process_cgroup,
    collect_process_stat,
    is_docker_scope,
    parse_proc_cgroup,
    parse_proc_stat,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_parse_four_real_cgroups() -> None:
    rows = (FIXTURES / "cgroup_real.txt").read_text().splitlines()
    for row in rows:
        assert parse_proc_cgroup(text="1:cpu:/legacy\n" + row) == row.removeprefix("0::")
    assert [is_docker_scope(path=row.removeprefix("0::")) for row in rows] == [
        False,
        False,
        False,
        True,
    ]
    assert is_docker_scope(path="/sys/fs/cgroup/system.slice/docker-abc.scope")
    assert not is_docker_scope(path="/user.slice/docker-abc.scope")
    assert not is_docker_scope(path="/system.slice/docker-.scope")


def test_proc_stat_with_spaces_and_parentheses() -> None:
    text = (FIXTURES / "proc_stat_parentheses.txt").read_text()
    assert parse_proc_stat(text=text) == (20, None)
    assert parse_proc_stat(text="123 (normal) S 10 20 30 34816 20") == (20, 20)


@pytest.mark.parametrize("text", ["", "1:cpu:/legacy", "0::"])
def test_cgroup_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_proc_cgroup(text=text)


@pytest.mark.parametrize("text", ["", "123 (name) S", "123 (name) S 1 x 3 4 5"])
def test_stat_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_proc_stat(text=text)


def test_process_readers(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    process = tmp_path / "123"
    process.mkdir()
    (process / "cgroup").write_text("0::/system.slice/docker-abc.scope\n")
    (process / "stat").write_text("123 (normal) S 10 20 30 34816 20")
    assert (
        collect_process_cgroup(pid=123, proc_root=tmp_path).data == "/system.slice/docker-abc.scope"
    )
    assert collect_process_stat(pid=123, proc_root=tmp_path).data == (20, 20)
    missing_cgroup = collect_process_cgroup(pid=456, proc_root=tmp_path)
    missing_stat = collect_process_stat(pid=456, proc_root=tmp_path)
    assert missing_cgroup.data is None
    assert missing_stat.data is None
    assert missing_cgroup.error is not None and missing_cgroup.error.endswith("456/cgroup'")
    assert missing_stat.error is not None and missing_stat.error.endswith("456/stat'")
    with caplog.at_level(level=logging.DEBUG):
        collect_process_cgroup(pid=456, proc_root=tmp_path)
        collect_process_stat(pid=456, proc_root=tmp_path)
    assert {record.levelno for record in caplog.records} == {logging.DEBUG}


def test_process_readers_report_unparsable_content_as_an_error(tmp_path: Path) -> None:
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "cgroup").write_text("1:cpu:/legacy\n")
    (tmp_path / "7" / "stat").write_text("7 (short) S")

    cgroup = collect_process_cgroup(pid=7, proc_root=tmp_path)
    stat = collect_process_stat(pid=7, proc_root=tmp_path)

    assert (cgroup.data, cgroup.error) == (None, "Missing unified cgroup path")
    assert (stat.data, stat.error) == (None, "Incomplete process stat")


def test_negative_process_groups_become_none() -> None:
    assert parse_proc_stat(text="123 (normal) S 10 -2 30 0 -1") == (None, None)


@pytest.mark.parametrize("filename", ["cgroup", "stat"])
@pytest.mark.parametrize(
    "failure",
    [
        (FileNotFoundError("gone"), logging.DEBUG),
        (ProcessLookupError("gone"), logging.DEBUG),
        (PermissionError("denied"), logging.WARNING),
        (ValueError("invalid"), logging.WARNING),
    ],
)
def test_process_read_error_log_levels(
    filename: str,
    failure: tuple[Exception, int],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error, level = failure

    def fail(self: Path) -> str:
        raise error

    monkeypatch.setattr(target=Path, name="read_text", value=fail)
    reader = collect_process_cgroup if filename == "cgroup" else collect_process_stat
    with caplog.at_level(level=logging.DEBUG):
        result = reader(pid=123)
    assert result.data is None
    assert result.error == str(error)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == level


def test_container_parsers() -> None:
    from wimm.collectors.cgroups import parse_cpu_stat, parse_memory_stat, parse_net_dev

    assert parse_memory_stat(text="anon 100\ninactive_file 30\n") == 30
    assert parse_cpu_stat(text="usage_usec 123\nuser_usec 100\n") == 123
    text = (
        "Inter-| Receive | Transmit\n face |bytes packets\n"
        " lo: 90 0 0 0 0 0 0 0 80 0\n eth0: 10 0 0 0 0 0 0 0 20 0\n"
    )
    assert parse_net_dev(text=text) == 30
    with pytest.raises(ValueError):
        parse_cpu_stat(text="user_usec 10")


def test_container_location_falls_back_to_proc(tmp_path: Path) -> None:
    from wimm.collectors.cgroups import locate_container_cgroup

    (tmp_path / "42").mkdir()
    (tmp_path / "42/cgroup").write_text("0::/user.slice/custom\n")
    custom = tmp_path / "user.slice/custom"
    custom.mkdir(parents=True)
    assert locate_container_cgroup(container_id="abc", pid=42, roots=(tmp_path, tmp_path)) == custom
    standard = tmp_path / "system.slice/docker-abc.scope"
    standard.mkdir(parents=True)
    assert (
        locate_container_cgroup(container_id="abc", pid=42, roots=(tmp_path, tmp_path)) == standard
    )
    assert (
        locate_container_cgroup(container_id="missing", pid=0, roots=(tmp_path, tmp_path)) is None
    )


def test_container_memory_clamps_and_reads_metrics(tmp_path: Path) -> None:
    from wimm.collectors.cgroups import read_container_metrics

    scope = tmp_path / "system.slice/docker-abc.scope"
    scope.mkdir(parents=True)
    (scope / "memory.current").write_text("20")
    (scope / "memory.stat").write_text("inactive_file 30")
    (scope / "cpu.stat").write_text("usage_usec 123")
    net = tmp_path / "42/net"
    net.mkdir(parents=True)
    (net / "dev").write_text("eth0: 10 0 0 0 0 0 0 0 20 0")
    assert read_container_metrics(container_id="abc", pid=42, roots=(tmp_path, tmp_path)) == (
        0,
        123,
        30,
    )


def test_parsers_on_captured_kernel_fixtures() -> None:
    from wimm.collectors.cgroups import parse_cpu_stat, parse_memory_stat, parse_net_dev

    assert parse_memory_stat(text=(FIXTURES / "memory_stat_real.txt").read_text()) == 18616320
    assert parse_cpu_stat(text=(FIXTURES / "cpu_stat_real.txt").read_text()) == 1314961415
    assert parse_net_dev(text=(FIXTURES / "net_dev_real.txt").read_text()) == 0
    text = "eth0: 10 0 0 0 0 0 0 0 20\nveth0: 30 0 0 0 0 0 0 0 40\nlo: 100 0 0 0 0 0 0 0 100"
    assert parse_net_dev(text=text) == 100


@pytest.mark.parametrize("filename", ["memory.current", "memory.stat", "cpu.stat"])
def test_unreadable_container_metric_returns_unavailable(tmp_path: Path, filename: str) -> None:
    from wimm.collectors.cgroups import read_container_metrics

    scope = tmp_path / "system.slice/docker-abc.scope"
    scope.mkdir(parents=True)
    for name, text in {
        "memory.current": "100",
        "memory.stat": "inactive_file 10",
        "cpu.stat": "usage_usec 1",
    }.items():
        if name != filename:
            (scope / name).write_text(text)
    assert read_container_metrics(container_id="abc", pid=42, roots=(tmp_path, tmp_path)) is None


LIBPOD_ID = "a" * 64
OTHER_LIBPOD_ID = "b" * 64


def _rootless_libpod_dir(root: Path, uid: int, name: str) -> Path:
    path = root / f"user.slice/user-{uid}.slice/user@{uid}.service/user.slice" / name
    path.mkdir(parents=True)
    return path


def test_locate_libpod_scope(tmp_path: Path) -> None:
    from wimm.collectors.cgroups import locate_libpod_scope

    scope = _rootless_libpod_dir(tmp_path, 1000, f"libpod-{LIBPOD_ID}.scope")
    _rootless_libpod_dir(tmp_path, 1000, f"libpod-conmon-{LIBPOD_ID}.scope")
    assert locate_libpod_scope(container_id=LIBPOD_ID, uid=1000, cgroup_root=tmp_path) == scope
    assert locate_libpod_scope(container_id=OTHER_LIBPOD_ID, uid=1000, cgroup_root=tmp_path) is None


def test_locate_libpod_scope_ignores_other_users_and_conmon_only(tmp_path: Path) -> None:
    from wimm.collectors.cgroups import locate_libpod_scope

    _rootless_libpod_dir(tmp_path, 1001, f"libpod-{LIBPOD_ID}.scope")
    _rootless_libpod_dir(tmp_path, 1000, f"libpod-conmon-{OTHER_LIBPOD_ID}.scope")
    assert locate_libpod_scope(container_id=LIBPOD_ID, uid=1000, cgroup_root=tmp_path) is None
    assert locate_libpod_scope(container_id=OTHER_LIBPOD_ID, uid=1000, cgroup_root=tmp_path) is None


@pytest.mark.parametrize("container_id", ["", "../x", "a/b", "*", "abc-def"])
def test_locate_libpod_scope_rejects_malformed_ids(tmp_path: Path, container_id: str) -> None:
    from wimm.collectors.cgroups import locate_libpod_scope

    _rootless_libpod_dir(tmp_path, 1000, f"libpod-{LIBPOD_ID}.scope")
    assert locate_libpod_scope(container_id=container_id, uid=1000, cgroup_root=tmp_path) is None


def test_podman_scope_patterns_match_container_and_conmon() -> None:
    from fnmatch import fnmatchcase

    from wimm.core.constants import PODMAN_SCOPE_PATTERNS

    def matches(name: str) -> bool:
        return any(fnmatchcase(name, pattern) for pattern in PODMAN_SCOPE_PATTERNS)

    assert matches(f"libpod-{LIBPOD_ID}.scope")
    assert matches(f"libpod-conmon-{LIBPOD_ID}.scope")
    assert not matches(f"docker-{LIBPOD_ID}.scope")
    assert not matches(f"libpod-{LIBPOD_ID}.service")


def test_locate_libpod_scope_search_failure_gives_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wimm.collectors.cgroups import locate_libpod_scope

    scope = _rootless_libpod_dir(tmp_path, 1000, f"libpod-{LIBPOD_ID}.scope")
    assert locate_libpod_scope(container_id=LIBPOD_ID, uid=1000, cgroup_root=tmp_path) == scope

    def fail(self: Path, pattern: str) -> list[Path]:
        raise PermissionError("denied")

    monkeypatch.setattr(target=Path, name="rglob", value=fail)

    assert locate_libpod_scope(container_id=LIBPOD_ID, uid=1000, cgroup_root=tmp_path) is None
