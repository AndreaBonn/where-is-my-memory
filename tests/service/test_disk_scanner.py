import os
from pathlib import Path

import pytest

from tests.core.disk_helpers import docker_disk
from wimm.collectors import CollectorResult
from wimm.config import Config
from wimm.model.disk import DockerDisk
from wimm.service.disk_scanner import RealDiskScanner, ScanCancelled

OLD_MTIME = 1_000_000_000  # 2001: far older than any minimum age


class CancellingDocker:
    """Docker answer that cancels the scan while it is being read, like a quit mid-scan."""

    def __init__(self) -> None:
        self.scanner: RealDiskScanner | None = None

    def collect(self) -> CollectorResult[DockerDisk]:
        if self.scanner is not None:
            self.scanner.cancel()
        return CollectorResult(data=docker_disk())


@pytest.fixture(autouse=True)
def xdg_cache_at_the_fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The scan reads the environment (R12): conftest points XDG_CACHE_HOME outside the fake
    home, where the table rightly refuses it, so put it where these tests build their caches."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "home" / ".cache"))


def _scanner(*, tmp_path: Path, docker: CancellingDocker) -> RealDiskScanner:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True)
    (home / ".cache" / "uv" / "wheel").write_bytes(b"x" * 5000)
    return RealDiskScanner(docker=docker, home=home, cache_dir=tmp_path / "sizes")


def test_scan_without_cancel_returns_the_report(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    result = scanner.scan(config=Config(devdirs_roots=(tmp_path / "home",)))
    assert [entry.kind.value for entry in result.caches] == ["uv"]


def test_cancel_during_the_scan_stops_it_before_the_next_phase(tmp_path: Path) -> None:
    docker = CancellingDocker()
    scanner = _scanner(tmp_path=tmp_path, docker=docker)
    docker.scanner = scanner
    with pytest.raises(ScanCancelled):
        scanner.scan(config=Config(devdirs_roots=(tmp_path / "home",)))
    assert not (tmp_path / "sizes").exists()


def test_scan_skips_a_missing_root_and_still_scans_the_others(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    home = tmp_path / "home"
    project = home / "code" / "app"
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "dep.js").write_bytes(b"x" * 4000)
    manifest = project / "package.json"
    manifest.write_text("{}", encoding="utf-8")
    for path in (manifest, project):
        os.utime(path, (OLD_MTIME, OLD_MTIME))
    config = Config(devdirs_roots=(home / "gone", home / "code"), devdirs_min_age_days=7)
    result = scanner.scan(config=config)
    assert [item.path for item in result.devdirs] == [str(project / "node_modules")]


def test_scan_with_only_a_missing_root_returns_a_report_without_devdirs(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    result = scanner.scan(config=Config(devdirs_roots=(tmp_path / "home" / "gone",)))
    assert result.devdirs == ()
    assert [entry.kind.value for entry in result.caches] == ["uv"]
