import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import pytest

from wimm.core.notify_types import NotificationState
from wimm.model.enums import GroupId
from wimm.paths import UserPaths
from wimm.service.history import EntityKey
from wimm.service.state_store import PersistedState, StateSaver, load_state

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def make_paths(tmp_path: Path) -> UserPaths:
    return UserPaths(config_dir=tmp_path, state_dir=tmp_path / "wimm-state", cache_dir=tmp_path)


def test_save_merges_live_last_active_into_the_kept_sections(tmp_path: Path) -> None:
    paths = make_paths(tmp_path=tmp_path)
    kept = PersistedState(ignored=frozenset({GroupId("g")}), notifications=NotificationState())
    live: dict[EntityKey, datetime] = {"c1": NOW}
    saver = StateSaver(paths=paths, state=kept, last_active=lambda: MappingProxyType(live))
    saver.save()
    loaded = load_state(paths=paths, now=NOW)
    assert dict(loaded.last_active) == {"c1": NOW}
    assert loaded.ignored == frozenset({GroupId("g")})


def test_close_saves_once_more_and_blocks_later_saves(tmp_path: Path) -> None:
    paths = make_paths(tmp_path=tmp_path)
    live: dict[EntityKey, datetime] = {"c1": NOW}
    saver = StateSaver(
        paths=paths, state=PersistedState(), last_active=lambda: MappingProxyType(live)
    )
    saver.close()
    live["c2"] = NOW + timedelta(minutes=1)
    saver.save()
    assert set(load_state(paths=paths, now=NOW).last_active) == {"c1"}


def test_write_failure_is_logged_and_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "wimm-state"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    saver = StateSaver(
        paths=make_paths(tmp_path=tmp_path),
        state=PersistedState(),
        last_active=lambda: MappingProxyType({}),
    )
    with caplog.at_level(logging.ERROR):
        saver.save()
    assert [r.levelno for r in caplog.records] == [logging.ERROR]


def test_unexpected_error_while_building_the_state_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken() -> dict[EntityKey, datetime]:
        raise RuntimeError("tracker exploded")

    saver = StateSaver(
        paths=make_paths(tmp_path=tmp_path), state=PersistedState(), last_active=broken
    )
    with caplog.at_level(logging.ERROR):
        saver.save()
        saver.close()
    assert [r.levelno for r in caplog.records] == [logging.ERROR, logging.ERROR]


def test_update_replaces_sections_and_save_round_trips_them_with_live_last_active(
    tmp_path: Path,
) -> None:
    paths = make_paths(tmp_path=tmp_path)
    until = NOW + timedelta(hours=24)
    live: dict[EntityKey, datetime] = {"c1": NOW}
    saver = StateSaver(
        paths=paths,
        state=PersistedState(ignored=frozenset({GroupId("old")})),
        last_active=lambda: MappingProxyType(live),
    )
    notifications = NotificationState(episodes=frozenset({(GroupId("n"), NOW)}))

    saver.update(
        changes={
            "ignored": frozenset({GroupId("new")}),
            "snoozes": {GroupId("s"): until},
            "notifications": notifications,
        }
    )
    saver.save()

    loaded = load_state(paths=paths, now=NOW)
    assert loaded.ignored == frozenset({GroupId("new")})
    assert dict(loaded.snoozes) == {GroupId("s"): until}
    assert loaded.notifications.episodes == notifications.episodes
    assert dict(loaded.last_active) == {"c1": NOW}
