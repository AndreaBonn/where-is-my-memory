from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wimm.config import (
    Config,
    load_config,
    parse_config,
    save_config,
    update_config,
)
from wimm.core.root_policy import RootRefusal
from wimm.paths import UserPaths


@pytest.fixture
def paths(tmp_path: Path) -> UserPaths:
    return UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )


def test_update_config_returns_new_config_without_mutating_inputs(tmp_path: Path) -> None:
    config = Config(sample_interval_s=60)
    changes = {"sample_interval_s": 120, "terminate_timeout_s": 9}
    snapshot = dict(changes)
    result = update_config(config=config, changes=changes, home=tmp_path)
    assert result.field_errors == {}
    assert result.config.sample_interval_s == 120
    assert result.config.terminate_timeout_s == 9
    assert config.sample_interval_s == 60
    assert changes == snapshot


def test_update_config_invalid_field_keeps_previous_value(tmp_path: Path) -> None:
    config = Config(sample_interval_s=60)
    result = update_config(
        config=config, changes={"sample_interval_s": 5, "terminate_timeout_s": 9}, home=tmp_path
    )
    assert set(result.field_errors) == {"sample_interval_s"}
    assert result.config.sample_interval_s == 60
    assert result.config.terminate_timeout_s == 9


def test_update_config_pressure_conflict_keeps_previous_pair(tmp_path: Path) -> None:
    config = Config(pressure_warning_pct=20, pressure_critical_pct=8)
    result = update_config(config=config, changes={"pressure_warning_pct": 6}, home=tmp_path)
    assert "pressure_critical_pct" in result.field_errors
    assert (result.config.pressure_warning_pct, result.config.pressure_critical_pct) == (20, 8)


def test_update_config_unknown_key_ignored_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    result = update_config(config=Config(), changes={"nope": 1}, home=tmp_path)
    assert result.config == Config()
    assert result.field_errors == {}
    assert "nope" in caplog.text


def test_saved_update_is_read_back(paths: UserPaths, tmp_path: Path) -> None:
    result = update_config(config=Config(), changes={"sample_interval_s": 45}, home=tmp_path)
    save_config(paths=paths, config=result.config, home=tmp_path)
    assert load_config(paths=paths, home=tmp_path).config.sample_interval_s == 45


def test_malformed_json_gives_defaults_with_warning(
    paths: UserPaths, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    paths.config_dir.mkdir(exist_ok=True)
    (paths.config_dir / "config.json").write_text('{"sample_interval_s": ', encoding="utf-8")
    with caplog.at_level("WARNING"):
        result = load_config(paths=paths, home=tmp_path)
    assert result.config == parse_config(raw={}, home=tmp_path).config
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_failed_write_keeps_old_file_and_leaves_no_temporary(
    paths: UserPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_config(paths=paths, config=Config(sample_interval_s=60), home=tmp_path)
    target = paths.config_dir / "config.json"
    before = target.read_bytes()

    def fail(*, src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("wimm.paths.os.replace", fail)
    with pytest.raises(OSError):
        save_config(paths=paths, config=Config(sample_interval_s=120), home=tmp_path)
    assert target.read_bytes() == before
    assert [p.name for p in paths.config_dir.iterdir()] == ["config.json"]


def test_config_exposes_the_refused_roots_with_their_reason() -> None:
    config = Config(devdirs_roots=(Path("/usr/share/fonts"),))
    assert config.refused_roots == ((Path("/usr/share/fonts"), RootRefusal.SYSTEM_PATH),)


def test_admitted_roots_leave_out_the_refused_ones(tmp_path: Path) -> None:
    # HOME is isolated under tmp_path/home; tmp_path itself sits under /tmp, a system prefix.
    inside = Path.home() / "code"
    outside = tmp_path / "elsewhere"
    inside.mkdir(parents=True)
    outside.mkdir()
    config = Config(devdirs_roots=(inside, outside))

    assert [root for root, _reason in config.refused_roots] == [outside]
    assert config.admitted_roots == (inside,)


def test_remote_sessions_flag_defaults_to_off() -> None:
    assert Config().remote_sessions_actionable is False


def test_remote_sessions_flag_round_trip(paths: UserPaths, tmp_path: Path) -> None:
    save_config(
        paths=paths, config=replace(Config(), remote_sessions_actionable=True), home=tmp_path
    )
    assert load_config(paths=paths, home=tmp_path).config.remote_sessions_actionable is True


def test_remote_sessions_flag_rejects_a_non_boolean(tmp_path: Path) -> None:
    result = parse_config(raw={"remote_sessions_actionable": 1}, home=tmp_path)
    assert "remote_sessions_actionable" in result.field_errors
    assert result.config.remote_sessions_actionable is False
    invalid: dict[str, Any] = {"remote_sessions_actionable": "yes"}
    with pytest.raises(ValueError):
        replace(Config(), **invalid)
