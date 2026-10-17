from typing import Any

import pytest

from wimm.config import RANGES, Config, config_to_raw
from wimm.model.enums import Category
from wimm.ui.dialogs.preferences_model import (
    GROUPS,
    NUMBER_FIELDS,
    actionable_categories,
    collect_changes,
    display_value,
    format_list,
    parse_list,
    raw_value,
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
    assert sorted(keys) == sorted(config_to_raw(config=Config()))
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
