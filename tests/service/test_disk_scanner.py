import logging
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.core.disk_helpers import docker_disk
from wimm.collectors import CollectorResult
from wimm.collectors.devdirs import DevDirScan
from wimm.collectors.ollama_models import OllamaScan
from wimm.config import Config
from wimm.core.ollama_served import ServedStore
from wimm.model.disk import DockerDisk
from wimm.service.disk_scanner import RealDiskScanner, ScanCancelled, build_disk_scanner

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


def _scanner(*, tmp_path: Path, docker: CancellingDocker, sizes: str = "sizes") -> RealDiskScanner:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True, exist_ok=True)
    (home / ".cache" / "uv" / "wheel").write_bytes(b"x" * 5000)
    return RealDiskScanner(docker=docker, home=home, cache_dir=tmp_path / sizes)


def test_scan_without_cancel_returns_the_report(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    result = scanner.scan(config=Config(devdirs_roots=(tmp_path / "home",)))
    assert [entry.kind.value for entry in result.caches] == ["uv"]


def test_cancel_during_the_scan_stops_it_before_the_next_phase(tmp_path: Path) -> None:
    config = Config(devdirs_roots=(tmp_path / "home",))
    _scanner(tmp_path=tmp_path, docker=CancellingDocker(), sizes="completed").scan(config=config)
    assert (tmp_path / "completed").is_dir()  # a scan that runs through creates its size cache

    docker = CancellingDocker()
    scanner = _scanner(tmp_path=tmp_path, docker=docker, sizes="cancelled")
    docker.scanner = scanner
    with pytest.raises(ScanCancelled):
        scanner.scan(config=config)
    assert not (tmp_path / "cancelled").exists()


def test_a_pause_after_cancel_raises_instead_of_sleeping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())

    def collect_caches(
        *, table: object, cache_dir: Path, sleep: Callable[[float], None]
    ) -> tuple[()]:
        scanner.cancel()
        sleep(3600)  # would hang the test for an hour if the pause did not check first
        return ()

    monkeypatch.setattr("wimm.service.disk_scanner.collect_caches", collect_caches)

    with pytest.raises(ScanCancelled):
        scanner.scan(config=Config(devdirs_roots=(tmp_path / "home",)))


def test_a_pause_without_cancel_returns_and_the_scan_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    pauses: list[float] = []

    def collect_caches(
        *, table: object, cache_dir: Path, sleep: Callable[[float], None]
    ) -> tuple[()]:
        sleep(0)
        pauses.append(0)
        return ()

    monkeypatch.setattr("wimm.service.disk_scanner.collect_caches", collect_caches)

    result = scanner.scan(config=Config(devdirs_roots=(tmp_path / "home",)))

    assert pauses == [0]
    assert result.caches == ()


def test_unreadable_entries_are_logged_at_info_with_their_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    monkeypatch.setattr(
        "wimm.service.disk_scanner.scan_devdirs",
        lambda **_: DevDirScan(devdirs=(), error_count=3),
    )
    config = Config(devdirs_roots=(tmp_path / "home",))

    with caplog.at_level(logging.INFO, logger="wimm.service.disk_scanner"):
        scanner.scan(config=config)
    assert "skipped 3 unreadable entries" in caplog.text
    assert [r.levelno for r in caplog.records] == [logging.INFO]

    caplog.clear()
    monkeypatch.setattr(
        "wimm.service.disk_scanner.scan_devdirs",
        lambda **_: DevDirScan(devdirs=(), error_count=0),
    )
    with caplog.at_level(logging.INFO, logger="wimm.service.disk_scanner"):
        scanner.scan(config=config)
    assert "unreadable" not in caplog.text


class FixedDocker:
    def collect(self) -> CollectorResult[DockerDisk]:
        return CollectorResult(data=docker_disk())


class NoOllama:
    def collect(self, **_: object) -> OllamaScan:
        return OllamaScan(entry=None, situation=ServedStore.NONE)


def test_build_disk_scanner_scans_the_given_home_and_keeps_sizes_in_the_given_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True)
    (home / ".cache" / "uv" / "wheel").write_bytes(b"x" * 5000)
    monkeypatch.setattr("wimm.service.disk_scanner.DockerDiskSource", FixedDocker)
    # Never the real ollama: this machine may run one.
    monkeypatch.setattr("wimm.service.disk_scanner.real_ollama_source", NoOllama)
    scanner = build_disk_scanner(home=home, cache_dir=tmp_path / "state")

    result = scanner.scan(config=Config(devdirs_roots=(home,)))

    assert [(entry.kind.value, entry.path) for entry in result.caches] == [
        ("uv", str(home / ".cache" / "uv"))
    ]
    assert (tmp_path / "state").is_dir()


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


def test_scan_never_walks_a_root_that_adr_007_refuses(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    # tmp_path sits under /tmp, a system prefix: a root there is refused, its folders unseen.
    project = tmp_path / "srv" / "app"
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "dep.js").write_bytes(b"x" * 4000)
    manifest = project / "package.json"
    manifest.write_text("{}", encoding="utf-8")
    for path in (manifest, project):
        os.utime(path, (OLD_MTIME, OLD_MTIME))
    config = Config(devdirs_roots=(tmp_path / "srv",), devdirs_min_age_days=7)

    assert config.refused_roots
    assert scanner.scan(config=config).devdirs == ()


def _old_project(*, root: Path, name: str) -> Path:
    project = root / name
    (project / "node_modules").mkdir(parents=True)
    (project / "node_modules" / "dep.js").write_bytes(b"x" * 4000)
    manifest = project / "package.json"
    manifest.write_text("{}", encoding="utf-8")
    for path in (manifest, project):
        os.utime(path, (OLD_MTIME, OLD_MTIME))
    return project


def test_scan_walks_an_admitted_root_outside_the_home_and_only_that_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = _scanner(tmp_path=tmp_path, docker=CancellingDocker())
    external = tmp_path / "data" / "code"
    not_admitted = tmp_path / "other" / "code"
    admitted_project = _old_project(root=external, name="app")
    _old_project(root=not_admitted, name="app")
    # The facts of the roots are ADR-007's business (tests/test_config_roots.py): here the
    # scan receives the verdict, and must walk exactly the roots it was handed.
    monkeypatch.setattr(
        "wimm.config.admitted_roots",
        lambda *, roots, home: tuple(r for r in roots if r == external),
    )
    config = Config(devdirs_roots=(external, not_admitted), devdirs_min_age_days=7)

    result = scanner.scan(config=config)

    assert [item.path for item in result.devdirs] == [str(admitted_project / "node_modules")]
