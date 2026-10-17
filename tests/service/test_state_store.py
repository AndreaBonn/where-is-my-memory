import json
import logging
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import pytest

from wimm.core.notify_rules import NotificationState
from wimm.model.enums import GroupId
from wimm.paths import UserPaths
from wimm.service import state_store
from wimm.service.state_store import PersistedState, load_state, save_state

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
GROUP = GroupId("project:/home/u/app")


@pytest.fixture
def paths(tmp_path: Path) -> UserPaths:
    return UserPaths(
        config_dir=tmp_path / "c", state_dir=tmp_path / "s" / "wimm", cache_dir=tmp_path / "k"
    )


def full_state() -> PersistedState:
    return PersistedState(
        last_active=MappingProxyType(
            {(4242, 1760000000.5): NOW - timedelta(hours=3), "abc123": NOW - timedelta(hours=5)}
        ),
        snoozes=MappingProxyType({GROUP: NOW + timedelta(hours=1)}),
        ignored=frozenset({GroupId("desktop:firefox")}),
        notifications=NotificationState(
            episodes=frozenset({(GROUP, NOW - timedelta(hours=2))}),
            pressure_sent=MappingProxyType({"ram": NOW - timedelta(minutes=10)}),
            sent_at=(NOW - timedelta(minutes=30),),
        ),
    )


def write_raw(paths: UserPaths, content: str) -> None:
    paths.state_dir.mkdir(parents=True)
    (paths.state_dir / state_store.STATE_FILE).write_text(content, encoding="utf-8")


def test_load_missing_file_returns_empty_state(paths: UserPaths) -> None:
    assert load_state(paths=paths, now=NOW) == PersistedState()


def test_round_trip_keeps_every_section(paths: UserPaths) -> None:
    save_state(paths=paths, state=full_state())
    assert load_state(paths=paths, now=NOW) == full_state()


def test_restart_keeps_the_idle_since_of_an_entity(paths: UserPaths) -> None:
    since = NOW - timedelta(hours=4)
    save_state(paths=paths, state=PersistedState(last_active=MappingProxyType({"c1": since})))
    assert load_state(paths=paths, now=NOW).last_active["c1"] == since


@pytest.mark.parametrize("content", ['{"version": 1, "last_ac', "", "[1, 2]", '{"version": 99}'])
def test_unreadable_file_gives_empty_state_and_warning(
    paths: UserPaths, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    write_raw(paths=paths, content=content)
    with caplog.at_level(logging.WARNING):
        assert load_state(paths=paths, now=NOW) == PersistedState()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_deeply_nested_json_gives_empty_state(
    paths: UserPaths, caplog: pytest.LogCaptureFixture
) -> None:
    write_raw(paths=paths, content="[" * 200000)
    with caplog.at_level(logging.WARNING):
        assert load_state(paths=paths, now=NOW) == PersistedState()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_truncated_real_file_gives_empty_state(
    paths: UserPaths, caplog: pytest.LogCaptureFixture
) -> None:
    save_state(paths=paths, state=full_state())
    target = paths.state_dir / state_store.STATE_FILE
    target.write_bytes(target.read_bytes()[:40])
    with caplog.at_level(logging.WARNING):
        assert load_state(paths=paths, now=NOW) == PersistedState()
    assert any("state" in r.getMessage() for r in caplog.records)


def test_expired_snooze_is_dropped_and_live_one_kept(paths: UserPaths) -> None:
    state = PersistedState(
        snoozes=MappingProxyType(
            {GroupId("old"): NOW - timedelta(seconds=1), GroupId("live"): NOW + timedelta(hours=1)}
        )
    )
    save_state(paths=paths, state=state)
    assert dict(load_state(paths=paths, now=NOW).snoozes) == {
        GroupId("live"): NOW + timedelta(hours=1)
    }


def test_invalid_entries_are_dropped_one_by_one(
    paths: UserPaths, caplog: pytest.LogCaptureFixture
) -> None:
    good_at = (NOW - timedelta(hours=1)).isoformat()
    raw = {
        "version": 1,
        "last_active": [
            {"container": "ok", "at": good_at},
            {"container": "naive", "at": "2026-10-16T10:00:00"},
            {"container": 7, "at": good_at},
            {"process": [True, 1.0], "at": good_at},
            {"process": [5, 9.5], "at": "not a date"},
            "junk",
        ],
        "ignored": ["keep", 3, ""],
        "snoozes": [
            {"group_id": "s", "until": (NOW + timedelta(hours=1)).isoformat()},
            {"until": 1},
        ],
        "episodes": [{"group_id": "g", "since": good_at}, {"group_id": "g"}],
        "pressure_sent": {"ram": good_at, "disk": "x", "": good_at},
        "sent_at": [good_at, "x", 4],
    }
    write_raw(paths=paths, content=json.dumps(raw))
    with caplog.at_level(logging.WARNING):
        loaded = load_state(paths=paths, now=NOW)
    assert set(loaded.last_active) == {"ok"}
    assert loaded.ignored == frozenset({GroupId("keep")})
    assert set(loaded.snoozes) == {GroupId("s")}
    assert len(loaded.notifications.episodes) == 1
    assert set(loaded.notifications.pressure_sent) == {"ram"}
    assert len(loaded.notifications.sent_at) == 1
    assert len(caplog.records) >= 10


def test_saved_file_is_private(paths: UserPaths) -> None:
    save_state(paths=paths, state=full_state())
    target = paths.state_dir / state_store.STATE_FILE
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.state_dir.stat().st_mode) == 0o700


def test_failed_write_leaves_previous_file_intact_and_no_temp(
    paths: UserPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_state(paths=paths, state=full_state())
    target = paths.state_dir / state_store.STATE_FILE
    before = target.read_bytes()

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        save_state(paths=paths, state=PersistedState())
    assert target.read_bytes() == before
    assert [p.name for p in paths.state_dir.iterdir()] == [state_store.STATE_FILE]
    assert load_state(paths=paths, now=NOW) == full_state()
