import json
from pathlib import Path

from scripts import build_badges

PASSED_LOG = (
    "tests/test_a.py ....s\n"
    "========== 14 passed, 1 skipped, 485 deselected in 59.78s (0:00:59) ==========\n"
)
FAILED_LOG = "FAILED tests/test_a.py::test_x\n===== 2 failed, 7 passed, 1 error in 3.10s =====\n"


def test_test_badge_counts_passed_tests_without_skipped() -> None:
    badge = build_badges.test_badge(pytest_log=PASSED_LOG)
    assert badge == {
        "schemaVersion": 1,
        "label": "tests",
        "message": "14 passed",
        "color": "brightgreen",
    }


def test_test_badge_reports_failures_in_red() -> None:
    badge = build_badges.test_badge(pytest_log=FAILED_LOG)
    assert badge["message"] == "7/10 passed"
    assert badge["color"] == "red"


def test_test_badge_without_summary_is_grey() -> None:
    badge = build_badges.test_badge(pytest_log="collected 0 items\n")
    assert badge["message"] == "no results"
    assert badge["color"] == "lightgrey"


def test_coverage_badge_rounds_total_and_picks_color() -> None:
    assert build_badges.coverage_badge(percent=84.6)["message"] == "85%"
    assert build_badges.coverage_badge(percent=84.6)["color"] == "green"
    assert build_badges.coverage_badge(percent=91.0)["color"] == "brightgreen"
    assert build_badges.coverage_badge(percent=70.0)["color"] == "yellow"
    assert build_badges.coverage_badge(percent=40.0)["color"] == "red"


def test_coverage_badge_color_matches_the_shown_percentage() -> None:
    badge = build_badges.coverage_badge(percent=89.6)
    assert badge["message"] == "90%"
    assert badge["color"] == "brightgreen"


def test_coverage_badge_without_data_is_grey() -> None:
    badge = build_badges.coverage_badge(percent=None)
    assert badge["message"] == "n/a"
    assert badge["color"] == "lightgrey"


def test_write_badges_creates_both_files(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(PASSED_LOG, encoding="utf-8")
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"totals": {"percent_covered": 84.6}}), encoding="utf-8")
    out = tmp_path / "badges"

    build_badges.write_badges(log_path=log, coverage_path=coverage, out_dir=out)

    tests = json.loads((out / "test-badge.json").read_text(encoding="utf-8"))
    cover = json.loads((out / "coverage-badge.json").read_text(encoding="utf-8"))
    assert tests["message"] == "14 passed"
    assert cover["message"] == "85%"


def test_write_badges_tolerates_missing_inputs(tmp_path: Path) -> None:
    out = tmp_path / "badges"

    build_badges.write_badges(
        log_path=tmp_path / "absent.log", coverage_path=tmp_path / "absent.json", out_dir=out
    )

    tests = json.loads((out / "test-badge.json").read_text(encoding="utf-8"))
    cover = json.loads((out / "coverage-badge.json").read_text(encoding="utf-8"))
    assert tests["color"] == "lightgrey"
    assert cover["color"] == "lightgrey"
