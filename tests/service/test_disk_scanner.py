from pathlib import Path

import pytest

from tests.core.disk_helpers import docker_disk
from wimm.collectors import CollectorResult
from wimm.config import Config
from wimm.model.disk import DockerDisk
from wimm.service.disk_scanner import RealDiskScanner, ScanCancelled


class CancellingDocker:
    """Docker answer that cancels the scan while it is being read, like a quit mid-scan."""

    def __init__(self) -> None:
        self.scanner: RealDiskScanner | None = None

    def collect(self) -> CollectorResult[DockerDisk]:
        if self.scanner is not None:
            self.scanner.cancel()
        return CollectorResult(data=docker_disk())


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
