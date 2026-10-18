from pathlib import Path

import pytest

from scripts.measure_open_time import (
    build_environment,
    first_window_id,
    format_summary,
    percentile,
    summarize,
)


def test_percentile_uses_nearest_rank_on_ten_samples() -> None:
    samples = [float(value) for value in range(10, 0, -1)]

    assert percentile(samples=samples, fraction=0.9) == 9.0
    assert percentile(samples=samples, fraction=0.5) == 5.0


def test_percentile_rejects_empty_samples() -> None:
    with pytest.raises(ValueError):
        percentile(samples=[], fraction=0.9)


def test_summarize_reports_median_and_p90() -> None:
    summary = summarize(samples=[0.4, 0.2, 0.3, 0.9])

    assert summary.count == 4
    assert summary.median_s == pytest.approx(0.35)
    assert summary.p90_s == 0.9


def test_format_summary_prints_milliseconds() -> None:
    line = format_summary(label="reopen", summary=summarize(samples=[0.1234, 0.2]))

    assert line == "reopen: n=2 median=162 ms p90=200 ms"


def test_first_window_id_takes_the_first_numeric_line() -> None:
    assert first_window_id(search_output="2097156\n2097160\n") == 2097156


@pytest.mark.parametrize("output", ["", "\n", "There are no windows in the stack\n"])
def test_first_window_id_none_without_a_window(output: str) -> None:
    assert first_window_id(search_output=output) is None


def test_build_environment_moves_home_and_xdg_under_root() -> None:
    env = build_environment(root=Path("/work/run"), base={"DISPLAY": ":99", "HOME": "/home/me"})

    assert env["HOME"] == "/work/run/home"
    assert env["XDG_STATE_HOME"] == "/work/run/state"
    assert env["DISPLAY"] == ":99"
    assert env["GSK_RENDERER"] == "cairo"
