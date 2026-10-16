from pathlib import Path
from types import SimpleNamespace

import pytest

from wimm.collectors.disk import collect_disk_usage
from wimm.model.memory import DiskUsage


class FakeFilesystem:
    def __init__(self, *, separate_home: bool = True) -> None:
        self.separate_home = separate_home

    def stat(self, path: Path) -> SimpleNamespace:
        device = 2 if self.separate_home and str(path).startswith("/home") else 1
        return SimpleNamespace(st_dev=device)

    def usage(self, path: Path) -> SimpleNamespace:
        return SimpleNamespace(total=100, used=60, free=40)


def test_disk_distinct_home_mount() -> None:
    fs = FakeFilesystem()
    result = collect_disk_usage(home=Path("/home/user"), stat=fs.stat, usage=fs.usage)
    assert result.data == (
        DiskUsage(mount="/", total=100, used=60, free=40),
        DiskUsage(mount="/home", total=100, used=60, free=40),
    )
    assert result.error is None


def test_disk_same_device_only_root() -> None:
    fs = FakeFilesystem(separate_home=False)
    result = collect_disk_usage(home=Path("/home/user"), stat=fs.stat, usage=fs.usage)
    assert result.data == (DiskUsage(mount="/", total=100, used=60, free=40),)


def test_disk_failure(caplog: pytest.LogCaptureFixture) -> None:
    def fail(path: Path) -> SimpleNamespace:
        raise OSError("unavailable")

    result = collect_disk_usage(usage=fail)
    assert result.data == () and result.error == "unavailable"
    assert "WARNING" in caplog.text


def test_home_stat_failure_preserves_root_usage() -> None:
    fs = FakeFilesystem()

    def stat(path: Path) -> SimpleNamespace:
        if path == Path("/home/user"):
            raise PermissionError("home unavailable")
        return fs.stat(path=path)

    result = collect_disk_usage(home=Path("/home/user"), stat=stat, usage=fs.usage)
    assert result.data == (DiskUsage(mount="/", total=100, used=60, free=40),)
    assert result.error == "home unavailable"
