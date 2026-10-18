from datetime import UTC, datetime, timedelta

from wimm.core import constants as c
from wimm.core.growth import GrowthTrend, growth_trend

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
MIB = 1024 * 1024
STEP_S = 600


def series(*, megabytes: list[int], end: datetime = NOW) -> list[tuple[datetime, int]]:
    """Points every 10 minutes, the last one at ``end``."""
    count = len(megabytes)
    return [
        (end - timedelta(seconds=STEP_S * (count - 1 - index)), value * MIB)
        for index, value in enumerate(megabytes)
    ]


def test_growth_trend_steady_rise_reports_delta_and_span() -> None:
    points = series(megabytes=[1000 + 40 * index for index in range(13)])

    trend = growth_trend(points=points, now=NOW)

    assert trend == GrowthTrend(delta_bytes=360 * MIB, span_s=2 * 3600)


def test_growth_trend_flat_series_is_not_growth() -> None:
    assert growth_trend(points=series(megabytes=[1500] * 18), now=NOW) is None


def test_growth_trend_sawtooth_is_not_growth() -> None:
    # a cache that fills and empties: ends high, but it came back down each time
    saw = [200, 700, 1200, 200, 700, 1200, 200, 700, 1200, 200, 700, 1200]
    assert growth_trend(points=series(megabytes=saw), now=NOW) is None


def test_growth_trend_rise_below_absolute_threshold_is_not_growth() -> None:
    # +40% but only 200 MiB
    assert growth_trend(points=series(megabytes=[500 + 17 * i for i in range(13)]), now=NOW) is None


def test_growth_trend_rise_below_relative_threshold_is_not_growth() -> None:
    # +360 MiB on 8000 MiB is under 20%
    assert (
        growth_trend(points=series(megabytes=[8000 + 40 * i for i in range(13)]), now=NOW) is None
    )


def test_growth_trend_too_short_series_is_none() -> None:
    assert growth_trend(points=series(megabytes=[100, 600, 1100, 1600]), now=NOW) is None
    assert growth_trend(points=[], now=NOW) is None


def test_growth_trend_short_span_is_none() -> None:
    # enough points, but all in the last 25 minutes
    points = [(NOW - timedelta(seconds=300 * (5 - i)), (100 + 400 * i) * MIB) for i in range(6)]
    assert growth_trend(points=points, now=NOW) is None


def test_growth_trend_enough_points_over_a_too_short_span_is_none() -> None:
    # 8 points (above GROWTH_MIN_POINTS) every 5 minutes: 35 minutes, under the minimum span
    points = [(NOW - timedelta(seconds=300 * (7 - i)), (100 + 400 * i) * MIB) for i in range(8)]

    assert len(points) > c.GROWTH_MIN_POINTS
    assert growth_trend(points=points, now=NOW) is None


def test_growth_trend_single_spike_is_not_growth() -> None:
    for spike in ([100] * 6 + [3000] + [100] * 6, [100] * 12 + [3000], [3000] + [100] * 12):
        assert growth_trend(points=series(megabytes=spike), now=NOW) is None


def test_growth_trend_out_of_order_points_are_sorted() -> None:
    points = series(megabytes=[1000 + 40 * index for index in range(13)])

    shuffled = points[6:] + points[:6]

    assert growth_trend(points=shuffled, now=NOW) == growth_trend(points=points, now=NOW)
    assert growth_trend(points=shuffled, now=NOW) is not None


def test_growth_trend_ignores_points_in_the_future() -> None:
    points = series(megabytes=[1000 + 40 * index for index in range(13)])
    future = [(NOW + timedelta(seconds=STEP_S), 9000 * MIB)]

    assert growth_trend(points=points + future, now=NOW) == growth_trend(points=points, now=NOW)


def test_growth_trend_only_future_points_is_none() -> None:
    future = series(megabytes=[100 + 500 * i for i in range(13)], end=NOW + timedelta(hours=3))
    assert growth_trend(points=future, now=NOW) is None


def test_growth_trend_ignores_points_older_than_the_window() -> None:
    old = series(megabytes=[5000] * 6, end=NOW - timedelta(hours=5))
    recent = series(megabytes=[1000 + 40 * index for index in range(13)])

    assert growth_trend(points=old + recent, now=NOW) == growth_trend(points=recent, now=NOW)


def test_growth_trend_tolerates_small_dips_in_a_real_rise() -> None:
    noisy = [1000, 1060, 1050, 1130, 1200, 1190, 1280, 1350, 1340, 1420, 1500, 1560]
    trend = growth_trend(points=series(megabytes=noisy), now=NOW)
    # medians of the first and last third: 1055 and 1460 MiB
    assert trend == GrowthTrend(delta_bytes=405 * MIB, span_s=11 * STEP_S)


def test_growth_trend_leak_with_sampling_jitter_is_growth() -> None:
    # about +25 MiB per sample (300 MiB over the series) with +-20 MiB of noise around it
    jitter = [0, 20, -20] * 6
    leak = [1000 + 25 * index + jitter[index] for index in range(18)]

    trend = growth_trend(points=series(megabytes=leak), now=NOW)

    # medians of the first and last third: 1060 and 1360 MiB
    assert trend == GrowthTrend(delta_bytes=300 * MIB, span_s=17 * STEP_S)


def test_growth_trend_falls_just_under_the_noise_floor_are_ignored() -> None:
    noise_mib = c.GROWTH_NOISE_BYTES // MIB
    # +40 MiB a step with every other step dipping by exactly the noise floor
    steps = [1000 + 40 * index - ((noise_mib + 40) if index % 2 else 0) for index in range(13)]

    assert growth_trend(points=series(megabytes=steps), now=NOW) is not None


def test_growth_trend_falls_over_the_noise_floor_still_count_as_sawtooth() -> None:
    noise_mib = c.GROWTH_NOISE_BYTES // MIB
    # the same dip one MiB over the floor: every fall counts again
    steps = [1000 + 40 * index - ((noise_mib + 41) if index % 2 else 0) for index in range(13)]

    assert growth_trend(points=series(megabytes=steps), now=NOW) is None


def test_growth_min_points_cover_the_minimum_span_at_the_sampling_interval() -> None:
    assert (c.GROWTH_MIN_POINTS - 1) * c.GROWTH_SAMPLE_INTERVAL_S >= c.GROWTH_MIN_SPAN_S
    assert (c.GROWTH_MIN_POINTS - 2) * c.GROWTH_SAMPLE_INTERVAL_S < c.GROWTH_MIN_SPAN_S


def test_growth_trend_seven_points_over_exactly_the_minimum_span_is_growth() -> None:
    trend = growth_trend(points=series(megabytes=[500 + 100 * i for i in range(7)]), now=NOW)

    assert trend == GrowthTrend(delta_bytes=500 * MIB, span_s=c.GROWTH_MIN_SPAN_S)
