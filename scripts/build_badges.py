"""Write the shields.io endpoint JSON for the README test and coverage badges.

Usage: ``uv run python scripts/build_badges.py PYTEST_LOG COVERAGE_JSON OUT_DIR``

The test count comes from the final pytest summary line of the CI run (``make test``); the
coverage from ``coverage json`` over the same run. A missing input gives a grey badge, so
CI still publishes something after a crash instead of keeping the previous numbers.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

Badge = dict[str, Any]

# "===== 2 failed, 7 passed, 1 error in 3.10s =====": the line pytest prints last.
SUMMARY_LINE = re.compile(r"\b\d+ (?:passed|failed|errors?)\b.* in [\d.]+s")
COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")
COVERAGE_COLORS = ((90.0, "brightgreen"), (80.0, "green"), (60.0, "yellow"))
GREY = "lightgrey"


def badge(*, label: str, message: str, color: str) -> Badge:
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def test_badge(*, pytest_log: str) -> Badge:
    """Badge for the last pytest summary in the log; skipped tests are not counted."""
    summaries = [line for line in pytest_log.splitlines() if SUMMARY_LINE.search(line)]
    if not summaries:
        return badge(label="tests", message="no results", color=GREY)
    counts = {"passed": 0, "failed": 0, "error": 0}
    for number, kind in COUNT.findall(summaries[-1]):
        counts["error" if kind.startswith("error") else kind] += int(number)
    broken = counts["failed"] + counts["error"]
    if broken:
        total = counts["passed"] + broken
        return badge(label="tests", message=f"{counts['passed']}/{total} passed", color="red")
    return badge(label="tests", message=f"{counts['passed']} passed", color="brightgreen")


def coverage_badge(*, percent: float | None) -> Badge:
    if percent is None:
        return badge(label="coverage", message="n/a", color=GREY)
    shown = round(percent)
    # The colour follows the number on the badge, not the unrounded one behind it.
    color = next((name for floor, name in COVERAGE_COLORS if shown >= floor), "red")
    return badge(label="coverage", message=f"{shown}%", color=color)


def read_coverage(*, path: Path) -> float | None:
    if not path.is_file():
        return None
    return float(json.loads(path.read_text(encoding="utf-8"))["totals"]["percent_covered"])


def write_badges(*, log_path: Path, coverage_path: Path, out_dir: Path) -> None:
    log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    badges = {
        "test-badge.json": test_badge(pytest_log=log),
        "coverage-badge.json": coverage_badge(percent=read_coverage(path=coverage_path)),
    }
    for name, content in badges.items():
        (out_dir / name).write_text(json.dumps(content) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pytest_log", type=Path)
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    write_badges(log_path=args.pytest_log, coverage_path=args.coverage_json, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
