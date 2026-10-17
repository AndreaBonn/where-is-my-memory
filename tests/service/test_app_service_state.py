from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest
from gi.repository import GLib

from tests.service.service_helpers import FakeSampler, spin_until
from wimm.config import Config
from wimm.core import constants as c
from wimm.paths import UserPaths
from wimm.service.app_service import AppService
from wimm.service.history import EntityKey
from wimm.service.state_store import STATE_FILE, PersistedState, StateSaver, load_state

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
LIVE: dict[EntityKey, datetime] = {"c1": NOW}


def make_service(tmp_path: Path) -> tuple[AppService, UserPaths]:
    paths = UserPaths(config_dir=tmp_path, state_dir=tmp_path / "wimm-state", cache_dir=tmp_path)
    saver = StateSaver(
        paths=paths, state=PersistedState(), last_active=lambda: MappingProxyType(LIVE)
    )
    sampler = FakeSampler()
    sampler.proceed.set()
    service = AppService(sampler=sampler, config=Config())
    service.attach_state_saver(saver=saver)
    return service, paths


def test_stop_writes_the_state_file(tmp_path: Path) -> None:
    service, paths = make_service(tmp_path=tmp_path)
    service.stop()
    assert dict(load_state(paths=paths, now=NOW).last_active) == LIVE


def test_start_schedules_a_save_every_five_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = make_service(tmp_path=tmp_path)
    calls: list[tuple[int, object]] = []

    def record(interval: int, callback: object, *args: object) -> int:
        calls.append((interval, callback))
        return len(calls)

    monkeypatch.setattr(GLib, "timeout_add_seconds", record)
    monkeypatch.setattr(GLib, "source_remove", lambda _tag: True)
    service.start()
    service.stop()
    assert c.STATE_SAVE_INTERVAL_S == 300
    assert [interval for interval, _ in calls] == [Config().sample_interval_s, 300]


def test_periodic_tick_saves_without_blocking_the_main_loop(tmp_path: Path) -> None:
    service, paths = make_service(tmp_path=tmp_path)
    try:
        assert service.save_state_tick() == GLib.SOURCE_CONTINUE
        spin_until(predicate=lambda: (paths.state_dir / STATE_FILE).exists())
    finally:
        service.stop()


def test_service_without_a_saver_stops_cleanly() -> None:
    service = AppService(sampler=FakeSampler(), config=Config())
    assert service.save_state_tick() == GLib.SOURCE_CONTINUE
    service.stop()
