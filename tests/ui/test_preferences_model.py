from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from wimm.config import RANGES, Config, config_to_raw
from wimm.core.root_policy import RootRefusal
from wimm.model.enums import Category
from wimm.ui.dialogs.preferences_model import (
    GROUPS,
    IMMEDIATE_KEYS,
    NUMBER_FIELDS,
    RootState,
    actionable_categories,
    collect_changes,
    display_value,
    format_list,
    parse_list,
    raw_value,
    root_statuses,
)


def test_display_value_converts_seconds_to_minutes() -> None:
    assert display_value(field=NUMBER_FIELDS["activity_window_s"], raw=1800) == 30


def test_display_value_converts_bytes_to_mebibytes() -> None:
    assert display_value(field=NUMBER_FIELDS["notify_min_bytes"], raw=209715200) == 200


def test_raw_value_round_trips_the_default_of_every_number_field() -> None:
    raw: dict[str, Any] = config_to_raw(config=Config())
    for key, field in NUMBER_FIELDS.items():
        shown = display_value(field=field, raw=raw[key])
        assert raw_value(field=field, shown=shown) == raw[key], key


def test_raw_value_returns_int_for_integer_fields_and_float_for_cpu() -> None:
    assert raw_value(field=NUMBER_FIELDS["sample_interval_s"], shown=45.0) == 45
    assert type(raw_value(field=NUMBER_FIELDS["sample_interval_s"], shown=45.0)) is int
    assert raw_value(field=NUMBER_FIELDS["cpu_active_threshold_pct"], shown=2.5) == 2.5
    assert type(raw_value(field=NUMBER_FIELDS["activity_window_s"], shown=10.0)) is int


def test_every_number_field_bounds_match_the_config_ranges() -> None:
    for key, field in NUMBER_FIELDS.items():
        lower, upper = RANGES[key]
        assert field.lower * field.factor == pytest.approx(lower), key
        if upper is not None:
            assert field.upper * field.factor == pytest.approx(upper), key


def test_groups_cover_every_config_field_but_nothing_unknown() -> None:
    keys = [key for group in GROUPS for key in group.keys]
    assert sorted([*keys, *IMMEDIATE_KEYS]) == sorted(config_to_raw(config=Config()))
    assert len(keys) == len(set(keys))


def test_parse_list_splits_on_commas_trims_and_drops_empty_items() -> None:
    assert parse_list(text=" gnome-shell, ,  sshd ,") == ["gnome-shell", "sshd"]
    assert parse_list(text="") == []


def test_format_list_joins_with_comma_and_space() -> None:
    assert format_list(items=["a", "b"]) == "a, b"
    assert format_list(items=[]) == ""


def test_actionable_categories_exclude_protected_ones() -> None:
    categories = actionable_categories()
    assert Category.PROJECT in categories
    assert Category.SYSTEM not in categories


def shown_from(raw: dict[str, Any]) -> dict[str, Any]:
    shown: dict[str, Any] = {}
    for key, value in raw.items():
        if key in NUMBER_FIELDS:
            shown[key] = display_value(field=NUMBER_FIELDS[key], raw=value)
        elif key in ("devdirs_roots", "extra_protected_names"):
            shown[key] = format_list(items=value)
        elif key == "notify_categories":
            shown[key] = frozenset(value)
        else:
            shown[key] = value
    return shown


def test_collect_changes_is_empty_when_nothing_was_touched() -> None:
    raw: dict[str, Any] = config_to_raw(config=Config())
    assert collect_changes(current=raw, shown=shown_from(raw)) == {}


def test_collect_changes_reports_only_the_edited_number_in_raw_units() -> None:
    raw: dict[str, Any] = config_to_raw(config=Config())
    shown = shown_from(raw)
    shown["activity_window_s"] = 60.0
    assert collect_changes(current=raw, shown=shown) == {"activity_window_s": 3600}


def test_collect_changes_ignores_rounding_of_values_not_multiple_of_the_unit() -> None:
    raw: dict[str, Any] = {**config_to_raw(config=Config()), **{"notify_min_bytes": 123456}}
    assert collect_changes(current=raw, shown=shown_from(raw)) == {}


def test_collect_changes_reports_lists_categories_and_booleans() -> None:
    raw: dict[str, Any] = config_to_raw(config=Config())
    shown = shown_from(raw)
    shown["extra_protected_names"] = "foo, bar"
    shown["notify_categories"] = frozenset({"PROJECT"})
    shown["foreground_tracking"] = False
    assert collect_changes(current=raw, shown=shown) == {
        "extra_protected_names": ["foo", "bar"],
        "notify_categories": ["PROJECT"],
        "foreground_tracking": False,
    }


def test_collect_changes_leaves_an_untouched_list_with_a_comma_alone() -> None:
    raw: dict[str, Any] = {
        **config_to_raw(config=Config()),
        "extra_protected_names": ["a,b", " padded "],
    }
    assert collect_changes(current=raw, shown=shown_from(raw)) == {}


def test_collect_changes_sends_an_edited_list_even_with_commas_in_the_old_one() -> None:
    raw: dict[str, Any] = {**config_to_raw(config=Config()), "extra_protected_names": ["a,b"]}
    shown = shown_from(raw)
    shown["extra_protected_names"] = "a,b, c"
    assert collect_changes(current=raw, shown=shown) == {"extra_protected_names": ["a", "b", "c"]}


ROOT_A = Path("/srv/a")
ROOT_B = Path("/srv/b")
ROOT_C = Path("/srv/c")
ROOT_D = Path("/srv/d")


def config_with_roots(
    *,
    monkeypatch: pytest.MonkeyPatch,
    roots: tuple[Path, ...],
    refused: tuple[tuple[Path, RootRefusal], ...] = (),
    missing: tuple[Path, ...] = (),
) -> Config:
    monkeypatch.setattr(Config, "refused_roots", property(lambda _self: refused))
    monkeypatch.setattr(Config, "missing_roots", property(lambda _self: missing))
    blocked = {*dict(refused), *missing}
    admitted = tuple(r for r in roots if r not in blocked)
    monkeypatch.setattr(Config, "admitted_roots", property(lambda _self: admitted))
    return replace(Config(), devdirs_roots=roots)


def test_root_statuses_tell_ok_missing_and_each_refusal_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reasons = (
        (ROOT_A, RootRefusal.SYSTEM_PATH),
        (ROOT_B, RootRefusal.NOT_OWNED),
        (ROOT_C, RootRefusal.REMOTE_FS),
    )
    roots = (ROOT_A, ROOT_B, ROOT_C, ROOT_D, Path("/srv/gone"))
    config = config_with_roots(
        monkeypatch=monkeypatch, roots=roots, refused=reasons, missing=(Path("/srv/gone"),)
    )
    statuses = root_statuses(config=config)
    assert [(s.path, s.state, s.reason) for s in statuses] == [
        (ROOT_A, RootState.REFUSED, RootRefusal.SYSTEM_PATH),
        (ROOT_B, RootState.REFUSED, RootRefusal.NOT_OWNED),
        (ROOT_C, RootState.REFUSED, RootRefusal.REMOTE_FS),
        (ROOT_D, RootState.OK, None),
        (Path("/srv/gone"), RootState.MISSING, None),
    ]


def test_root_statuses_without_problems_are_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    config = config_with_roots(monkeypatch=monkeypatch, roots=(ROOT_D,))
    assert [s.state for s in root_statuses(config=config)] == [RootState.OK]


def test_display_value_rejects_a_stored_value_that_is_not_a_number() -> None:
    field = NUMBER_FIELDS["activity_window_s"]
    assert display_value(field=field, raw=1800) == 30
    for wrong in ("1800", None, [1800]):
        with pytest.raises(TypeError, match="activity_window_s: expected a number"):
            display_value(field=field, raw=wrong)


def test_format_list_rejects_a_stored_value_that_is_not_a_list() -> None:
    assert format_list(items=["a", "b"]) == "a, b"
    for wrong in ("a, b", None, 3):
        with pytest.raises(TypeError, match="expected a list"):
            format_list(items=wrong)


def test_collect_changes_rejects_a_shown_number_of_the_wrong_type() -> None:
    raw: dict[str, Any] = config_to_raw(config=Config())
    ok = {"sample_interval_s": 45}
    assert collect_changes(current=raw, shown=ok) == {"sample_interval_s": 45}
    # A bool is an int to Python, but a switch state is not a number of seconds.
    for wrong in ("45", None, True):
        with pytest.raises(TypeError, match="sample_interval_s: expected a number"):
            collect_changes(current=raw, shown={"sample_interval_s": wrong})
