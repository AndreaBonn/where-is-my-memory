from datetime import UTC, datetime, timedelta, timezone

import pytest

from wimm.model.enums import ActionKind, ActivityState, Category, Pressure, Risk
from wimm.ui.format import (
    ACTION_LABELS,
    CATEGORY_LABELS,
    PRESSURE_TEXT,
    RISK_CONSEQUENCE,
    RISK_STYLE,
    RISK_TEXT,
    activity_text,
    allocate_percents,
    button_label,
    fold_text,
    format_clock,
    format_elapsed,
    format_round_size,
    format_size,
)

from ..helpers import invalid_model_value

ROME = timezone(timedelta(hours=2))


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (999, "999 B"),
        (1_000, "1 kB"),
        (1_500, "2 kB"),
        (980_000_000, "980 MB"),
        (999_000_000, "999 MB"),
        (999_499_999, "999 MB"),
        (999_500_000, "1,0 GB"),
        (1_000_000_000, "1,0 GB"),
        (1_050_000_000, "1,1 GB"),
        (1_049_999_999, "1,0 GB"),
        (38_900_000_000, "38,9 GB"),
        (30_100_000_000, "30,1 GB"),
        (999_950_000_000, "1,0 TB"),
        (10**15, "1000,0 TB"),
    ],
)
def test_format_size_si_units_with_italian_comma(size: int, expected: str) -> None:
    assert format_size(size=size) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "da 0 s"),
        (59, "da 59 s"),
        (60, "da 1 min"),
        (12 * 60 + 30, "da 12 min"),
        (3599, "da 59 min"),
        (3600, "da 1 h"),
        (5 * 3600 + 1080, "da 5 h"),
        (86399, "da 23 h"),
        (86400, "da 1 giorno"),
        (3 * 86400 + 5, "da 3 giorni"),
    ],
)
def test_format_elapsed_picks_unit_and_floors(seconds: float, expected: str) -> None:
    assert format_elapsed(seconds=seconds) == expected


@pytest.mark.parametrize(
    ("sizes", "expected"),
    [
        ((1, 1, 1), (34, 33, 33)),
        ((50, 50), (50, 50)),
        ((0, 10), (0, 100)),
        ((1, 999), (0, 100)),
        ((2, 1, 1), (50, 25, 25)),
        ((0, 0), (0, 0)),
        ((), ()),
    ],
)
def test_allocate_percents_sums_to_100_by_largest_remainder(
    sizes: tuple[int, ...], expected: tuple[int, ...]
) -> None:
    assert allocate_percents(sizes=sizes) == expected


def test_allocate_percents_gives_extra_points_to_largest_remainders() -> None:
    result = allocate_percents(sizes=(1, 2, 4))
    assert result == (14, 29, 57)
    assert sum(result) == 100


def test_fold_text_drops_accents_and_case() -> None:
    assert fold_text(text="Attività ÈÙ") == "attivita eu"
    assert fold_text(text="plain") == "plain"


@pytest.mark.parametrize("size", [-1, float("nan"), float("inf")])
def test_format_size_rejects_values_outside_the_contract(size: float) -> None:
    with pytest.raises(ValueError, match="size"):
        format_size(size=invalid_model_value(size))


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf"), float("-inf")])
def test_format_elapsed_rejects_values_outside_the_contract(seconds: float) -> None:
    with pytest.raises(ValueError, match="seconds"):
        format_elapsed(seconds=seconds)


def test_format_clock_same_day_shows_time_only() -> None:
    now = datetime(2026, 10, 16, 10, 30, tzinfo=ROME)
    assert format_clock(value=datetime(2026, 10, 16, 5, 12, tzinfo=ROME), now=now) == "05:12"


def test_format_clock_other_day_adds_date() -> None:
    now = datetime(2026, 10, 16, 10, 30, tzinfo=ROME)
    assert format_clock(value=datetime(2026, 10, 15, 23, 5, tzinfo=ROME), now=now) == "15/10 23:05"


def test_activity_text_active_and_idle() -> None:
    assert activity_text(state=ActivityState.ACTIVE, reason="x", elapsed_s=10) == "in uso"
    idle = activity_text(state=ActivityState.IDLE, reason="x", elapsed_s=5 * 3600 + 60)
    assert idle == "non in uso da 5 h"


def test_activity_text_idle_without_elapsed_is_zero_seconds() -> None:
    assert (
        activity_text(state=ActivityState.IDLE, reason="x", elapsed_s=None) == "non in uso da 0 s"
    )


def test_activity_text_unknown_distinguishes_observing_from_unmeasurable() -> None:
    observing = activity_text(
        state=ActivityState.UNKNOWN, reason="in osservazione da 4 minuti", elapsed_s=None
    )
    unmeasurable = activity_text(
        state=ActivityState.UNKNOWN, reason="attività non misurabile per i browser", elapsed_s=None
    )
    assert observing == "in osservazione"
    assert unmeasurable == "attività non misurabile"


def test_button_labels_carry_no_ellipsis() -> None:
    # D7: every action asks for confirmation, so no label marks the ones that do.
    labels = [button_label(kind=kind) for kind in ActionKind]
    assert labels == [ACTION_LABELS[kind] for kind in ActionKind]
    assert not [label for label in labels if label.endswith("…")]
    assert button_label(kind=ActionKind.GROUP_STOP) == "Ferma"


def test_every_enum_member_has_a_label() -> None:
    assert set(ACTION_LABELS) == set(ActionKind)
    assert set(CATEGORY_LABELS) == set(Category)
    assert set(RISK_TEXT) == set(RISK_STYLE) == set(RISK_CONSEQUENCE) == set(Risk)
    assert set(PRESSURE_TEXT) == set(Pressure)
    assert all(label.strip() for label in ACTION_LABELS.values())


def test_labels_match_spec_wording() -> None:
    assert [RISK_TEXT[r] for r in Risk] == ["Sicuro", "Attenzione", "Pericolo"]
    assert [RISK_STYLE[r] for r in Risk] == ["success", "warning", "error"]
    assert CATEGORY_LABELS[Category.PROJECT] == "Progetto"
    assert CATEGORY_LABELS[Category.DEV_PROCESS] == "Strumento di sviluppo"


def test_category_labels_avoid_jargon() -> None:
    assert CATEGORY_LABELS[Category.AI_CLI] == "Assistente AI"
    assert CATEGORY_LABELS[Category.DEV_SERVER] == "Server di sviluppo"
    assert CATEGORY_LABELS[Category.CONTAINER] == "Contenitore Docker"


@pytest.mark.parametrize(
    ("risk", "text"),
    [
        (Risk.SAFE, "Sicuro: non perdi nulla"),
        (Risk.CAUTION, "Attenzione: puoi perdere lavoro"),
        (Risk.DANGER, "Pericolo: cancella dati"),
    ],
)
def test_risk_consequence_names_the_risk_and_what_is_lost(risk: Risk, text: str) -> None:
    assert RISK_CONSEQUENCE[risk] == text


@pytest.mark.parametrize(
    ("size", "text"),
    [(32_900_000_000, "33 GB"), (9_840_000_000, "9,8 GB"), (980_000_000, "980 MB"), (0, "0 B")],
)
def test_format_round_size_drops_decimals_from_10_gb(size: int, text: str) -> None:
    assert format_round_size(size=size) == text


def test_format_clock_shows_utc_values_in_the_system_time_zone() -> None:
    # The service clock is UTC: 03:58 UTC is 05:58 in Rome in October (CEST).
    now = datetime(2026, 10, 17, 4, 0, tzinfo=UTC)
    assert format_clock(value=datetime(2026, 10, 17, 3, 58, tzinfo=UTC), now=now) == "05:58"


def test_format_clock_compares_days_in_the_system_time_zone() -> None:
    # 23:30 UTC on the 16th is 01:30 on the 17th in Rome: same local day as now.
    now = datetime(2026, 10, 17, 6, 0, tzinfo=UTC)
    value = datetime(2026, 10, 16, 23, 30, tzinfo=UTC)
    assert format_clock(value=value, now=now) == "01:30"
    assert format_clock(value=value - timedelta(hours=2), now=now) == "16/10 23:30"


def test_short_date_puts_the_day_first_in_italian() -> None:
    from datetime import datetime

    from wimm.ui.format import short_date

    assert short_date(moment=datetime(2026, 10, 16, 9, 5)) == "16/10"
