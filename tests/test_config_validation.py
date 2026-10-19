from pathlib import Path
from typing import Any

import pytest

from wimm.config import (
    RANGES,
    Config,
    parse_config,
)
from wimm.core import constants as c
from wimm.model import Category

CATEGORIES_MESSAGE = "notify_categories must contain actionable categories"
NAMES_MESSAGE = "extra_protected_names must be a tuple of strings"
ROOTS_MESSAGE = "devdirs_roots must be a tuple of absolute paths"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"notify_categories": frozenset({"PROJECT"})}, CATEGORIES_MESSAGE),
        ({"notify_categories": [Category.PROJECT]}, CATEGORIES_MESSAGE),
        ({"extra_protected_names": ["custom"]}, NAMES_MESSAGE),
        ({"extra_protected_names": (1,)}, NAMES_MESSAGE),
        ({"extra_protected_names": ("",)}, NAMES_MESSAGE),
        ({"devdirs_roots": []}, ROOTS_MESSAGE),
        ({"devdirs_roots": [Path("/home")]}, ROOTS_MESSAGE),
        ({"devdirs_roots": (Path("relative"),)}, ROOTS_MESSAGE),
    ],
)
def test_constructor_rejects_invalid_collections(values: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
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
                    # The warning limit is 50 too, so a critical threshold of 50 is never
                    # below it: the order rule refuses it and the defaults come back.
                    refused = parse_config(
                        raw={name: 50, "pressure_warning_pct": 50}, home=tmp_path
                    )
                    assert set(refused.field_errors) == {"pressure_critical_pct"}
                    assert refused.config.pressure_critical_pct == c.PRESSURE_CRITICAL_PCT
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
    assert result.config.devdirs_roots == ()


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
