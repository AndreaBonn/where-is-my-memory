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
    assert collect_process_cgroup(pid=456, proc_root=tmp_path).error
    assert collect_process_stat(pid=456, proc_root=tmp_path).error
    with caplog.at_level(level=logging.DEBUG):
        assert collect_process_cgroup(pid=456, proc_root=tmp_path).error
        assert collect_process_stat(pid=456, proc_root=tmp_path).error
    assert {record.levelno for record in caplog.records} == {logging.DEBUG}


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
