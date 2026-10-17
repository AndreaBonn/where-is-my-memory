from pathlib import Path

import pytest
from gi.repository import GLib

from tests.service.service_helpers import FakeSampler
from wimm.config import Config, load_config
from wimm.paths import UserPaths
from wimm.service.app_service import AppService


@pytest.fixture
def paths(tmp_path: Path) -> UserPaths:
    return UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )


def test_update_config_saves_and_applies_new_values(paths: UserPaths, tmp_path: Path) -> None:
    service = AppService(sampler=FakeSampler(), config=Config())
    result = service.update_config(changes={"terminate_timeout_s": 9}, paths=paths, home=tmp_path)
    assert result.field_errors == {}
    assert service.config().terminate_timeout_s == 9
    assert load_config(paths=paths, home=tmp_path).config.terminate_timeout_s == 9


def test_update_config_invalid_field_reports_error_and_keeps_value(
    paths: UserPaths, tmp_path: Path
) -> None:
    service = AppService(sampler=FakeSampler(), config=Config())
    result = service.update_config(changes={"sample_interval_s": 5}, paths=paths, home=tmp_path)
    assert set(result.field_errors) == {"sample_interval_s"}
    assert service.config().sample_interval_s == Config().sample_interval_s


def test_new_sample_interval_reschedules_running_timer(
    paths: UserPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[int] = []
    removed: list[int] = []

    def add(interval: int, callback: object) -> int:
        scheduled.append(interval)
        return len(scheduled)

    monkeypatch.setattr(GLib, "timeout_add_seconds", add)
    monkeypatch.setattr(GLib, "source_remove", removed.append)
    sampler = FakeSampler()
    sampler.proceed.set()
    service = AppService(sampler=sampler, config=Config(sample_interval_s=30))
    try:
        service.start()
        service.update_config(changes={"sample_interval_s": 60}, paths=paths, home=tmp_path)
        assert scheduled == [30, 60]
        assert removed == [1]
    finally:
        service.stop()


def test_update_config_before_start_does_not_create_timer(
    paths: UserPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[int] = []

    def add(interval: int, callback: object) -> int:
        scheduled.append(interval)
        return 1

    monkeypatch.setattr(GLib, "timeout_add_seconds", add)
    service = AppService(sampler=FakeSampler(), config=Config())
    service.update_config(changes={"sample_interval_s": 60}, paths=paths, home=tmp_path)
    assert scheduled == []


def test_failed_save_leaves_running_config_unchanged(
    paths: UserPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*, src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("wimm.paths.os.replace", fail)
    service = AppService(sampler=FakeSampler(), config=Config())
    with pytest.raises(OSError):
        service.update_config(changes={"terminate_timeout_s": 9}, paths=paths, home=tmp_path)
    assert service.config().terminate_timeout_s == Config().terminate_timeout_s
