from pathlib import Path

import pytest

from wimm.collectors.pressure import read_oom_kills, read_psi
from wimm.model.raw import PsiSample

PSI_TEXT = (
    "some avg10=1.50 avg60=12.34 avg300=3.00 total=430543553\n"
    "full avg10=0.00 avg60=5.67 avg300=0.10 total=403890083\n"
)
EVENTS_TEXT = "low 0\nhigh 0\nmax 0\noom 0\noom_kill 6\noom_group_kill 0\nsock_throttled 105259\n"
UID = 1234


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _events(root: Path, text: str) -> Path:
    unit = root / f"user.slice/user-{UID}.slice/user@{UID}.service"
    return _write(unit / "memory.events", text)


def test_read_psi_returns_avg60_of_some_and_full(tmp_path: Path) -> None:
    path = _write(tmp_path / "memory", PSI_TEXT)

    assert read_psi(path=path) == PsiSample(some_avg60=12.34, full_avg60=5.67)


def test_read_psi_missing_file_gives_none(tmp_path: Path) -> None:
    assert read_psi(path=tmp_path / "absent") is None


def test_read_psi_one_malformed_line_gives_none(tmp_path: Path) -> None:
    path = _write(tmp_path / "memory", "some avg10=1 avg60=abc total=1\nfull avg10=0 avg60=2.50\n")

    # The core compares both averages, so a half-read sample is no sample.
    assert read_psi(path=path) is None


@pytest.mark.parametrize("text", ["", "garbage\n", "some avg10=1.00\n", "other avg60=4.00\n"])
def test_read_psi_malformed_text_gives_none(tmp_path: Path, text: str) -> None:
    path = _write(tmp_path / "memory", text)

    assert read_psi(path=path) is None


def test_read_oom_kills_reads_the_user_manager_counter(tmp_path: Path) -> None:
    _events(tmp_path, EVENTS_TEXT)

    assert read_oom_kills(uid=UID, cgroup_root=tmp_path) == 6


def test_read_oom_kills_ignores_the_other_oom_counters(tmp_path: Path) -> None:
    _events(tmp_path, "oom 9\noom_group_kill 8\n")

    assert read_oom_kills(uid=UID, cgroup_root=tmp_path) is None


def test_read_oom_kills_missing_file_gives_none(tmp_path: Path) -> None:
    assert read_oom_kills(uid=UID, cgroup_root=tmp_path) is None


@pytest.mark.parametrize("text", ["", "oom_kill\n", "oom_kill abc\n", "oom_kill -3\n"])
def test_read_oom_kills_malformed_gives_none(tmp_path: Path, text: str) -> None:
    _events(tmp_path, text)

    assert read_oom_kills(uid=UID, cgroup_root=tmp_path) is None


def test_read_oom_kills_other_user_cgroup_is_not_read(tmp_path: Path) -> None:
    _events(tmp_path, EVENTS_TEXT)

    assert read_oom_kills(uid=UID + 1, cgroup_root=tmp_path) is None


def test_read_psi_negative_average_gives_none(tmp_path: Path) -> None:
    path = _write(tmp_path / "memory", "some avg10=0 avg60=-1.00\nfull avg10=0 avg60=2.00\n")

    assert read_psi(path=path) is None
