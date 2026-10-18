"""Measure RNF-04: time from an open request to the panel window mapped on screen.

Run it under a private bus and a virtual display, like ``make perf``:

    dbus-run-session -- xvfb-run -a uv run python -m scripts.measure_open_time

It starts ``python -m wimm --background``, sends ``org.freedesktop.Application.Activate``
(the call behind the tray click) and polls X (``xdotool search --onlyvisible --pid``) until
a window of that process is mapped. The clock includes about 10 ms of process spawn on each
side and stops at the map, not at the first paint. Cases: first open (new process each
time, GTK to load) and reopen (same process, closed with WM_DELETE_WINDOW in between).
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from statistics import median
from time import monotonic, sleep

from scripts.xwindow_close import request_close

LOGGER = logging.getLogger("measure_open_time")
APP_ID = "io.github.wimm.WhereIsMyMemory"
OBJECT_PATH = "/io/github/wimm/WhereIsMyMemory"
REPO_ROOT = Path(__file__).resolve().parent.parent
REPETITIONS = 10
P90_FRACTION = 0.9
START_TIMEOUT_S = 20.0
WINDOW_TIMEOUT_S = 60.0
SETTLE_S = 3.0  # lets the first sampling cycle finish: it is not part of the open request
POLL_S = 0.005
RENDER_ENV = {"GSK_RENDERER": "cairo", "GDK_DEBUG": "gl-disable,vulkan-disable"}
WELCOMED_RELATIVE = Path("state") / "where-is-my-memory" / "welcomed"


# Called through an alias, as in wimm.service.fs_controls: the argv is built here, never from input.
_RUN: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run
TOOL_TIMEOUT_S = 90
GDBUS_TIMEOUT_S = 60


def tool_path(*, name: str) -> str:
    """Absolute path of a required tool, or a clear failure when it is missing."""
    found = shutil.which(name)
    if found is None:
        raise SystemExit(f"{name} is required by this script and was not found on PATH")
    return found


@dataclass(frozen=True)
class Summary:
    count: int
    median_s: float
    p90_s: float


def percentile(*, samples: list[float], fraction: float) -> float:
    """Nearest-rank percentile: the smallest sample with at least ``fraction`` below it."""
    if not samples:
        raise ValueError("percentile of an empty sample list")
    ordered = sorted(samples)
    return ordered[max(ceil(fraction * len(ordered)) - 1, 0)]


def summarize(*, samples: list[float]) -> Summary:
    """Median and 90th percentile of the samples, in seconds."""
    return Summary(
        count=len(samples),
        median_s=median(samples),
        p90_s=percentile(samples=samples, fraction=P90_FRACTION),
    )


def first_window_id(*, search_output: str) -> int | None:
    """First window id printed by ``xdotool search``, or None when there is none."""
    for line in search_output.splitlines():
        if line.strip().isdigit():
            return int(line.strip())
    return None


def format_summary(*, label: str, summary: Summary) -> str:
    return (
        f"{label}: n={summary.count} median={summary.median_s * 1000:.0f} ms "
        f"p90={summary.p90_s * 1000:.0f} ms"
    )


def build_environment(*, root: Path, base: dict[str, str]) -> dict[str, str]:
    """Environment with HOME and every XDG directory under ``root``."""
    env = {**base, **RENDER_ENV, "HOME": str(root / "home")}
    for name, folder in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_DATA_HOME", "data"),
    ):
        env[name] = str(root / folder)
    return env


def prepare_root(*, root: Path) -> None:
    """Create the temporary home and mark the welcome as seen, so --background stays hidden."""
    (root / "home").mkdir(parents=True, exist_ok=True)
    marker = root / WELCOMED_RELATIVE
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def _gdbus(*, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _RUN(
        [tool_path(name="gdbus"), "call", "--session", "--timeout", str(GDBUS_TIMEOUT_S), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=TOOL_TIMEOUT_S,
    )


def _name_is_owned() -> bool:
    result = _gdbus(
        args=[
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.NameHasOwner",
            APP_ID,
        ]
    )
    return "true" in result.stdout


def start_app(*, env: dict[str, str], log_path: Path) -> subprocess.Popen[bytes]:
    """Start the resident process and wait until it owns its bus name and settles."""
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            args=[sys.executable, "-m", "wimm", "--background"],
            env=env,
            cwd=REPO_ROOT,
            stdout=log,
            stderr=log,
        )
    deadline = monotonic() + START_TIMEOUT_S
    while not _name_is_owned():
        if process.poll() is not None or monotonic() > deadline:
            process.kill()  # A timed-out start would otherwise outlive the script.
            raise RuntimeError(f"The app did not start, see {log_path}")
        sleep(0.05)
    sleep(SETTLE_S)
    return process


def stop_app(*, process: subprocess.Popen[bytes]) -> None:
    _gdbus(
        args=[
            "--dest",
            APP_ID,
            "--object-path",
            OBJECT_PATH,
            "--method",
            "org.gtk.Actions.Activate",
            "quit",
            "[]",
            "{}",
        ]
    )
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)


def visible_window(*, pid: int) -> int | None:
    result = _RUN(
        [tool_path(name="xdotool"), "search", "--onlyvisible", "--pid", str(pid)],
        capture_output=True,
        text=True,
        check=False,
        timeout=TOOL_TIMEOUT_S,
    )
    return first_window_id(search_output=result.stdout)


def time_open(*, pid: int) -> float:
    """Seconds from the Activate call to a mapped window of ``pid``."""
    started = monotonic()
    _gdbus(
        args=[
            "--dest",
            APP_ID,
            "--object-path",
            OBJECT_PATH,
            "--method",
            "org.freedesktop.Application.Activate",
            "{}",
        ]
    )
    while visible_window(pid=pid) is None:
        if monotonic() - started > WINDOW_TIMEOUT_S:
            raise RuntimeError("No mapped window appeared")
        sleep(POLL_S)
    return monotonic() - started


def close_window(*, pid: int) -> None:
    """Hide the panel as the user does, and wait until it is no longer mapped."""
    window = visible_window(pid=pid)
    if window is None:
        return
    request_close(window=window)
    deadline = monotonic() + WINDOW_TIMEOUT_S
    while visible_window(pid=pid) is not None:
        if monotonic() > deadline:
            raise RuntimeError("The window did not hide")
        sleep(POLL_S)
    sleep(0.3)


def warm_up(*, root: Path, env: dict[str, str]) -> None:
    """One discarded open: on a fresh private bus it activates the desktop portal (about 25 s)."""
    process = start_app(env=env, log_path=root / "warmup.log")
    try:
        time_open(pid=process.pid)
    finally:
        stop_app(process=process)


def measure_first_open(*, root: Path, env: dict[str, str], repetitions: int) -> list[float]:
    """One fresh process per repetition, so GTK is loaded by the measured request."""
    samples = []
    for index in range(repetitions):
        process = start_app(env=env, log_path=root / f"first-{index}.log")
        try:
            samples.append(time_open(pid=process.pid))
        finally:
            stop_app(process=process)
    return samples


def measure_reopen(*, root: Path, env: dict[str, str], repetitions: int) -> list[float]:
    """One process: a warm-up open loads GTK, then each sample reopens the hidden window."""
    process = start_app(env=env, log_path=root / "reopen.log")
    samples = []
    try:
        time_open(pid=process.pid)
        for _ in range(repetitions):
            close_window(pid=process.pid)
            samples.append(time_open(pid=process.pid))
    finally:
        stop_app(process=process)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    parser.add_argument("--workdir", type=Path, default=None, help="parent of the temporary HOME")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="wimm-open-", dir=args.workdir))
    prepare_root(root=root)
    env = build_environment(root=root, base=dict(os.environ))
    try:
        warm_up(root=root, env=env)
        for label, measure in (("first open", measure_first_open), ("reopen", measure_reopen)):
            samples = measure(root=root, env=env, repetitions=args.repetitions)
            print(format_summary(label=label, summary=summarize(samples=samples)))
            print(f"{label} samples (ms): {[round(value * 1000) for value in samples]}")
    except Exception:
        LOGGER.error("Measurement failed; logs kept in %s", root)
        raise
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
