from pathlib import Path
from types import SimpleNamespace

import pytest

from wimm.collectors.disk import collect_disk_usage
from wimm.model.memory import DiskUsage


class FakeFilesystem:
    """Device 2 holds ``separate_mount`` and everything below it; every other path is device 1."""

    def __init__(self, *, separate_mount: Path | None) -> None:
        self.separate_mount = separate_mount

    def stat(self, path: Path) -> SimpleNamespace:
        mount = self.separate_mount
        on_mount = mount is not None and (path == mount or mount in path.parents)
        return SimpleNamespace(st_dev=2 if on_mount else 1)

    def usage(self, path: Path) -> SimpleNamespace:
        return SimpleNamespace(total=100, used=60, free=40)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A home folder below a fake mount point, both real folders of this test."""
    folder = tmp_path.resolve() / "mnt" / "user"
    folder.mkdir(parents=True)
    return folder


def test_disk_distinct_home_mount(home: Path) -> None:
    mount = home.parent
    fs = FakeFilesystem(separate_mount=mount)
    result = collect_disk_usage(home=home, stat=fs.stat, usage=fs.usage)
    assert result.data == (
        DiskUsage(mount="/", total=100, used=60, free=40),
        DiskUsage(mount=str(mount), total=100, used=60, free=40),
    )
    assert result.error is None


def test_disk_same_device_only_root(home: Path) -> None:
    fs = FakeFilesystem(separate_mount=None)
    result = collect_disk_usage(home=home, stat=fs.stat, usage=fs.usage)
    assert result.data == (DiskUsage(mount="/", total=100, used=60, free=40),)


def test_disk_failure(caplog: pytest.LogCaptureFixture) -> None:
    def fail(path: Path) -> SimpleNamespace:
        raise OSError("unavailable")

    result = collect_disk_usage(usage=fail)
    assert result.data == () and result.error == "unavailable"
    assert "WARNING" in caplog.text


def test_home_stat_failure_preserves_root_usage(home: Path) -> None:
    fs = FakeFilesystem(separate_mount=home.parent)

    def stat(path: Path) -> SimpleNamespace:
        if path == home:
            raise PermissionError("home unavailable")
        return fs.stat(path=path)

    result = collect_disk_usage(home=home, stat=stat, usage=fs.usage)
    assert result.data == (DiskUsage(mount="/", total=100, used=60, free=40),)
    assert result.error == "home unavailable"
