"""The status labels, durations and tables of ui/format.py in English."""

import pytest

from wimm.i18n import _
from wimm.model.enums import ActionKind, ActivityState, Category, Pressure, Risk
from wimm.ui.format import (
    CATEGORY_LABELS,
    PRESSURE_TEXT,
    RISK_CONSEQUENCE,
    RISK_TEXT,
    activity_text,
    button_label,
    format_elapsed,
    format_growth,
)

pytestmark = pytest.mark.usefixtures("english")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (5, "for 5 s"),
        (300, "for 5 min"),
        (3 * 3600, "for 3 h"),
        (86400, "for 1 day"),
        (3 * 86400, "for 3 days"),
    ],
)
def test_format_elapsed_in_english_picks_unit_and_plural(seconds: float, expected: str) -> None:
    assert format_elapsed(seconds=seconds) == expected


def test_activity_text_reads_in_english_for_each_state() -> None:
    idle = activity_text(state=ActivityState.IDLE, reason="x", elapsed_s=7200)
    unknown = activity_text(state=ActivityState.UNKNOWN, reason="x", elapsed_s=None)
    assert activity_text(state=ActivityState.ACTIVE, reason="x", elapsed_s=None) == "in use"
    assert idle == "not in use for 2 h"
    assert unknown == "activity cannot be measured"


def test_activity_text_keeps_the_observing_reason_apart_from_other_unknowns() -> None:
    observing = activity_text(
        state=ActivityState.UNKNOWN, reason="observing for 4 minutes", elapsed_s=None
    )
    assert observing == "observing"


def test_the_tables_translate_where_they_are_shown() -> None:
    assert _(CATEGORY_LABELS[Category.DEV_SERVER]) == "Development server"
    assert _(CATEGORY_LABELS[Category.CONTAINER]) == "Docker container"
    assert [_(RISK_TEXT[risk]) for risk in Risk] == ["Safe", "Caution", "Danger"]
    assert _(RISK_CONSEQUENCE[Risk.CAUTION]) == "Caution: you may lose work"
    assert [_(PRESSURE_TEXT[p]) for p in Pressure] == ["Normal", "High", "Critical"]


def test_the_tables_keep_the_italian_source_so_that_identities_do_not_move() -> None:
    # The English run reads the same keys and values the Italian run stores.
    assert CATEGORY_LABELS[Category.DEV_SERVER] == "Server di sviluppo"
    assert RISK_TEXT[Risk.DANGER] == "Pericolo"


def test_button_labels_are_english() -> None:
    assert button_label(kind=ActionKind.CONTAINER_STOP) == "Stop"
    assert button_label(kind=ActionKind.STOP_ALL_IDLE_SAFE) == "Free the memory"


def test_short_date_puts_the_month_first_in_english() -> None:
    from datetime import datetime

    from wimm.ui.format import short_date

    assert short_date(moment=datetime(2026, 10, 16, 9, 5)) == "10/16"


def test_format_clock_on_another_day_puts_the_month_first() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from wimm.ui.format import format_clock

    rome = ZoneInfo("Europe/Rome")
    now = datetime(2026, 10, 16, 9, 0, tzinfo=rome)
    assert format_clock(value=datetime(2026, 10, 15, 23, 5, tzinfo=rome), now=now) == "10/15 23:05"


@pytest.mark.parametrize(
    ("span_s", "expected"),
    [(7200, "+620 MB in 2 h"), (2400, "+620 MB in 40 minutes"), (60, "+620 MB in 1 minute")],
)
def test_format_growth_in_english(span_s: int, expected: str) -> None:
    assert format_growth(delta_bytes=620_000_000, span_s=span_s) == expected
