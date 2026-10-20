"""T-6.37c: the system ollama entry joins the disk scan like the other caches (D4)."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.core.disk_helpers import docker_disk
from tests.core.ollama_system_helpers import system_entry
from wimm.collectors import CollectorResult
from wimm.collectors.ollama_models import OllamaScan
from wimm.config import Config
from wimm.core.cache_catalog import CacheResolution
from wimm.core.disk_rules import safe_reclaimable_bytes
from wimm.core.ollama_served import ServedStore
from wimm.model import CacheEntry
from wimm.model.disk import DiskReport, DockerDisk
from wimm.service.disk_scanner import RealDiskScanner, build_disk_scanner

UV_BYTES = 5000


class FixedDocker:
    def collect(self) -> CollectorResult[DockerDisk]:
        return CollectorResult(data=docker_disk())


class FakeOllama:
    """Records what the scan hands over; answers with a fixed entry (or none)."""

    def __init__(
        self, *, entry: CacheEntry | None, situation: ServedStore = ServedStore.SYSTEM
    ) -> None:
        self.entry = entry
        self.situation = situation
        self.calls: list[tuple[Path, CacheResolution, tuple[CacheEntry, ...]]] = []

    def collect(
        self, *, home: Path, table: CacheResolution, caches: tuple[CacheEntry, ...]
    ) -> OllamaScan:
        self.calls.append((home, table, caches))
        return OllamaScan(entry=self.entry, situation=self.situation)


@pytest.fixture(autouse=True)
def xdg_cache_at_the_fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "home" / ".cache"))


def _scan_report(*, tmp_path: Path, ollama: FakeOllama | None) -> DiskReport:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True)
    (home / ".cache" / "uv" / "wheel").write_bytes(b"x" * UV_BYTES)
    scanner = RealDiskScanner(
        docker=FixedDocker(), home=home, cache_dir=tmp_path / "sizes", ollama=ollama
    )
    return scanner.scan(config=Config(devdirs_roots=(home,)))


def _scan(*, tmp_path: Path, ollama: FakeOllama | None) -> tuple[CacheEntry, ...]:
    return _scan_report(tmp_path=tmp_path, ollama=ollama).caches


def test_the_system_entry_joins_the_report_caches_and_is_sorted_with_them(tmp_path: Path) -> None:
    entry = system_entry(size=3_000_000)
    ollama = FakeOllama(entry=entry)
    caches = _scan(tmp_path=tmp_path, ollama=ollama)
    assert [c.kind.value for c in caches] == ["ollama_system", "uv"]
    assert caches[0] == entry


def test_the_collector_gets_the_home_the_start_up_table_and_the_caches_found(
    tmp_path: Path,
) -> None:
    ollama = FakeOllama(entry=None)
    _scan(tmp_path=tmp_path, ollama=ollama)
    ((home, table, found),) = ollama.calls
    assert home == tmp_path / "home"
    assert any(cache.kind.value == "uv" for cache in table.caches)
    assert [c.kind.value for c in found] == ["uv"]


def test_no_entry_leaves_the_report_as_before(tmp_path: Path) -> None:
    caches = _scan(tmp_path=tmp_path, ollama=FakeOllama(entry=None))
    assert [c.kind.value for c in caches] == ["uv"]


def test_without_an_ollama_source_the_scan_does_not_look_for_one(tmp_path: Path) -> None:
    assert [c.kind.value for c in _scan(tmp_path=tmp_path, ollama=None)] == ["uv"]


def test_the_system_entry_is_never_counted_as_safe_to_reclaim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "uv").mkdir(parents=True)
    (home / ".cache" / "uv" / "wheel").write_bytes(b"x" * UV_BYTES)
    scanner = RealDiskScanner(
        docker=FixedDocker(),
        home=home,
        cache_dir=tmp_path / "sizes",
        ollama=FakeOllama(entry=system_entry(size=3_000_000)),
    )
    report = scanner.scan(config=Config(devdirs_roots=(home,)))
    with_entry = safe_reclaimable_bytes(report=report)
    without = safe_reclaimable_bytes(report=replace(report, caches=()))
    uv_size = next(c.size for c in report.caches if c.kind.value == "uv")
    assert with_entry - without == uv_size  # uv counts, the ollama entry adds nothing


def test_the_running_application_scanner_uses_the_real_ollama_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    entry = system_entry(size=3_000_000)
    monkeypatch.setattr("wimm.service.disk_scanner.DockerDiskSource", FixedDocker)
    monkeypatch.setattr(
        "wimm.service.disk_scanner.real_ollama_source", lambda: FakeOllama(entry=entry)
    )
    report = build_disk_scanner(home=home, cache_dir=tmp_path / "state").scan(
        config=Config(devdirs_roots=(home,))
    )
    assert report.caches == (entry,)


@pytest.mark.parametrize("situation", list(ServedStore))
def test_the_report_keeps_the_server_situation_even_without_a_system_entry(
    tmp_path: Path, situation: ServedStore
) -> None:
    report = _scan_report(tmp_path=tmp_path, ollama=FakeOllama(entry=None, situation=situation))
    assert report.ollama_served == situation.value


def test_the_report_has_no_situation_when_the_scan_has_no_ollama_source(tmp_path: Path) -> None:
    assert _scan_report(tmp_path=tmp_path, ollama=None).ollama_served == ""
