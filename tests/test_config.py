import json
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wimm.config import (
    RANGES,
    Config,
    config_to_raw,
    load_config,
    parse_config,
    save_config,
    update_config,
)
from wimm.core import constants as c
from wimm.model import Category
from wimm.paths import UserPaths


@pytest.fixture
def paths(tmp_path: Path) -> UserPaths:
    return UserPaths(
        config_dir=tmp_path / "config", state_dir=tmp_path / "state", cache_dir=tmp_path / "cache"
    )


def test_defaults_and_protected_union(tmp_path: Path) -> None:
    result = parse_config(raw={}, home=tmp_path)
    assert result.field_errors == {}
    assert result.config.sample_interval_s == c.SAMPLE_INTERVAL_S
    assert result.config.devdirs_roots == (tmp_path / "Documenti/00_Lavoro",)
    config = replace(result.config, extra_protected_names=("custom",))
    assert config.protected_names == frozenset((*c.PROTECTED_PROCESS_NAMES, "custom"))
    assert result.config.extra_protected_names == ()


@pytest.mark.parametrize("field", sorted(RANGES))
def test_ranges_rejected_by_parser_and_constructor(field: str, tmp_path: Path) -> None:
    lower, upper = RANGES[field]
    for value in (lower - 1, *(() if upper is None else (upper + 1,)), True, "wrong"):
        result = parse_config(raw={field: value}, home=tmp_path)
        assert field in result.field_errors
        assert getattr(result.config, field) == getattr(Config(), field)
        with pytest.raises(ValueError):
            replace(Config(), **{field: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), False, None])
def test_float_invalid_values(value: object, tmp_path: Path) -> None:
    result = parse_config(raw={"cpu_active_threshold_pct": value}, home=tmp_path)
    assert result.config.cpu_active_threshold_pct == c.CPU_ACTIVE_THRESHOLD_PCT
    assert "cpu_active_threshold_pct" in result.field_errors


def test_pressure_cross_validation(tmp_path: Path) -> None:
    result = parse_config(
        raw={"pressure_warning_pct": 5, "pressure_critical_pct": 5}, home=tmp_path
    )
    assert result.config.pressure_warning_pct == c.PRESSURE_WARNING_PCT
    assert result.config.pressure_critical_pct == c.PRESSURE_CRITICAL_PCT
    assert (
        "deve essere minore della soglia di avviso"
        in result.field_errors["pressure_critical_pct"].lower()
    )
    with pytest.raises(ValueError, match="pressure"):
        Config(pressure_warning_pct=10, pressure_critical_pct=10)


def test_categories_and_unknown_keys(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    result = parse_config(raw={"notify_categories": ["PROJECT"], "unknown": 9}, home=tmp_path)
    assert result.config.notify_categories == frozenset({Category.PROJECT})
    assert result.field_errors == {}
    assert "unknown" in caplog.text
    for value in (["SYSTEM"], ["missing"], "PROJECT", [True]):
        result = parse_config(raw={"notify_categories": value}, home=tmp_path)
        assert "notify_categories" in result.field_errors
    with pytest.raises(ValueError):
        Config(notify_categories=frozenset({Category.SELF}))


def test_roots_expand_and_reject_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    link = tmp_path / "escape"
    link.symlink_to(target=tmp_path.parent, target_is_directory=True)
    result = parse_config(raw={"devdirs_roots": ["~/project"]}, home=tmp_path)
    assert result.config.devdirs_roots == (root,)
    for value in ([str(link)], ["~/missing"], ["relative"], [42], "~/project", [], [""]):
        result = parse_config(raw={"devdirs_roots": value}, home=tmp_path)
        assert "devdirs_roots" in result.field_errors
        assert result.config.devdirs_roots == (tmp_path / "Documenti/00_Lavoro",)


def test_collections_and_boolean_validation(tmp_path: Path) -> None:
    for field, value in (
        ("extra_protected_names", [42]),
        ("extra_protected_names", "x"),
        ("extra_protected_names", [""]),
        ("foreground_tracking", 1),
    ):
        result = parse_config(raw={field: value}, home=tmp_path)
        assert field in result.field_errors
    config = parse_config(
        raw={"extra_protected_names": ["mine"], "foreground_tracking": False}, home=tmp_path
    ).config
    assert config.extra_protected_names == ("mine",)
    assert config.foreground_tracking is False
    invalid: dict[str, Any] = {"foreground_tracking": 1}
    with pytest.raises(ValueError):
        replace(Config(), **invalid)


def test_save_load_round_trip(paths: UserPaths, tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    config = parse_config(
        raw={"devdirs_roots": [str(root)], "sample_interval_s": 60}, home=tmp_path
    ).config
    save_config(paths=paths, config=config)
    assert load_config(paths=paths, home=tmp_path).config == config
    assert load_config(paths=paths, home=tmp_path).field_errors == {}
    assert stat.S_IMODE((paths.config_dir / "config.json").stat().st_mode) == 0o600
    assert json.loads((paths.config_dir / "config.json").read_text()) == config_to_raw(
        config=config
    )
    assert config_to_raw(config=config)["devdirs_roots"] == [str(root)]


@pytest.mark.parametrize("content", ["{", "[]", "null", "\udcff"])
def test_corrupt_file_defaults(
    paths: UserPaths, content: str, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    paths.config_dir.mkdir(exist_ok=True)
    (paths.config_dir / "config.json").write_bytes(content.encode(errors="surrogateescape"))
    result = load_config(paths=paths, home=tmp_path)
    assert result.config.sample_interval_s == c.SAMPLE_INTERVAL_S
    assert "WARNING" in caplog.text


def test_missing_file_defaults(paths: UserPaths, tmp_path: Path) -> None:
    result = load_config(paths=paths, home=tmp_path)
    assert result.config.sample_interval_s == c.SAMPLE_INTERVAL_S
    assert result.field_errors == {}


@pytest.mark.parametrize(
    "values",
    [
        {"notify_categories": frozenset({"PROJECT"})},
        {"notify_categories": [Category.PROJECT]},
        {"extra_protected_names": ["custom"]},
        {"extra_protected_names": (1,)},
        {"extra_protected_names": ("",)},
        {"devdirs_roots": ()},
        {"devdirs_roots": [Path("/home")]},
        {"devdirs_roots": (Path("relative"),)},
    ],
)
def test_constructor_rejects_invalid_collections(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Config(**values)


def test_valid_range_boundaries_and_fractional_integer_rejection(tmp_path: Path) -> None:
    for name, (lower, upper) in RANGES.items():
        for boundary in (lower, upper):
            if boundary is None:
                continue
            raw = {name: boundary}
            if name == "pressure_warning_pct":
                raw["pressure_critical_pct"] = c.PRESSURE_CRITICAL_PCT - 9
            if name == "pressure_critical_pct":
                raw["pressure_warning_pct"] = c.PRESSURE_WARNING_PCT + 35
                if boundary == 50:
                    continue
            result = parse_config(raw=raw, home=tmp_path)
            assert result.field_errors == {}
            assert getattr(result.config, name) == boundary
        if name != "cpu_active_threshold_pct":
            result = parse_config(raw={name: lower + 0.5}, home=tmp_path)
            assert name in result.field_errors


@pytest.mark.parametrize("root", ["project", ""])
def test_relative_existing_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(path=tmp_path)
    result = parse_config(raw={"devdirs_roots": [root]}, home=tmp_path)
    assert "devdirs_roots" in result.field_errors
    assert result.config.devdirs_roots == (tmp_path / "Documenti/00_Lavoro",)


def test_sample_interval_below_range_gives_field_error_and_default(tmp_path: Path) -> None:
    result = parse_config(raw={"sample_interval_s": 5, "activity_window_s": 600}, home=tmp_path)
    assert result.config.sample_interval_s == c.SAMPLE_INTERVAL_S
    assert set(result.field_errors) == {"sample_interval_s"}
    assert result.config.activity_window_s == 600


def test_unknown_key_logs_warning_and_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        result = parse_config(raw={"bogus_key": 1}, home=tmp_path)
    assert result.config == parse_config(raw={}, home=tmp_path).config
    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert "bogus_key" in caplog.text


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
    save_config(paths=paths, config=result.config)
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
    save_config(paths=paths, config=Config(sample_interval_s=60))
    target = paths.config_dir / "config.json"
    before = target.read_bytes()

    def fail(*, src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("wimm.paths.os.replace", fail)
    with pytest.raises(OSError):
        save_config(paths=paths, config=Config(sample_interval_s=120))
    assert target.read_bytes() == before
    assert [p.name for p in paths.config_dir.iterdir()] == ["config.json"]
