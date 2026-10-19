"""Rows, empty states and the summary header of the overview in English."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from tests.ui.viewmodel_helpers import make_group, roomy_disk, with_groups
from wimm.core import text
from wimm.model.enums import ActivityState, Category, Pressure
from wimm.model.snapshot import Snapshot
from wimm.ui.viewmodel import build_rows, build_summary, empty_state
from wimm.ui.views import EmptyKind, RowFilters

pytestmark = pytest.mark.usefixtures("english")


def _idle_reason() -> str:
    facts = text.IdleFacts(
        window_s=1800, cpu_avg_pct=0.1, net_avg_bps=None, watches_connections=True, open_port=None
    )
    return text.reason_idle(idle_for_s=5 * 3600, facts=facts, from_monitor_start=False)


def test_an_idle_group_row_reads_in_english(snapshot: Snapshot, now: datetime) -> None:
    group = make_group(
        "whitebox", category=Category.PROJECT, reason=_idle_reason(), ports=(8000, 8080)
    )

    (row,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)

    assert row.subtitle == "Project · not in use for 5 h"
    assert row.detail == "You haven't used it for 5 hours: nobody connects to it."
    assert row.technical.endswith(" · ports 8000, 8080")
    assert (row.risk_text, row.primary_action.label if row.primary_action else "") == (
        "Safe: you lose nothing",
        "Stop",
    )


def test_one_port_is_singular(snapshot: Snapshot, now: datetime) -> None:
    group = make_group("web", reason=_idle_reason(), ports=(8000,))

    (row,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)

    assert row.technical.endswith(" · port 8000")


def test_the_badge_without_an_action_is_english(snapshot: Snapshot, now: datetime) -> None:
    group = make_group("gnome", risk=None)

    (row,) = build_rows(snapshot=with_groups(snapshot, group), filters=RowFilters(), now=now)

    assert row.risk_text == "No action"


def test_subtitle_for_each_activity_state_in_english(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("a", category=Category.DEV_SERVER, state=ActivityState.ACTIVE),
        make_group(
            "b",
            category=Category.BROWSER,
            reason=text.reason_unmeasurable(category=Category.OTHER),
            state=ActivityState.UNKNOWN,
            since=None,
        ),
        make_group(
            "c",
            category=Category.AI_CLI,
            reason=text.reason_observing(elapsed_s=240),
            state=ActivityState.UNKNOWN,
            since=None,
        ),
    )

    rows = {
        r.title: r.subtitle
        for r in build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    }

    assert rows == {
        "a": "Development server · in use",
        "b": "Browser · activity cannot be measured",
        "c": "AI assistant · observing",
    }


def test_snooze_text_in_english(snapshot: Snapshot, now: datetime) -> None:
    groups = (
        make_group("future", snoozed_until=now + timedelta(hours=1)),
        make_group("tomorrow", snoozed_until=datetime(2026, 10, 17, 14, 30, tzinfo=now.tzinfo)),
    )

    rows = {
        r.title: r
        for r in build_rows(snapshot=with_groups(snapshot, *groups), filters=RowFilters(), now=now)
    }

    assert rows["future"].snoozed_text == "alerts paused until 11:30"
    assert rows["tomorrow"].snoozed_text == "alerts paused until 10/17 at 14:30"


def test_empty_states_in_english(snapshot: Snapshot) -> None:
    active = with_groups(snapshot, make_group(state=ActivityState.ACTIVE))
    idle_only = empty_state(snapshot=active, filters=RowFilters(only_idle=True))
    none = empty_state(snapshot=with_groups(snapshot), filters=RowFilters())
    narrowed = empty_state(snapshot=snapshot, filters=RowFilters(query="zzz"))

    assert idle_only is not None and idle_only.kind is EmptyKind.NOTHING_IDLE
    assert idle_only.message == "Nothing to free: the rest is in use or still being watched."
    assert none is not None and none.message == "All clear"
    assert none.description == (
        "Nothing is running that can be closed. We'll tell you if something stays on for no reason."
    )
    assert narrowed is not None and narrowed.message == "No program matches the filters."


def test_summary_headlines_and_legend_in_english(snapshot: Snapshot) -> None:
    summary = build_summary(snapshot=snapshot)
    ram_tight = build_summary(snapshot=roomy_disk(snapshot))

    assert summary.ram_headline == "33 GB used of 42 GB"
    assert summary.ram_details == "8.8 GB available · swap 120 MB of 4.3 GB"
    assert ram_tight.ram_details.endswith(" · memory almost full")
    assert summary.disk_headline == "28 GB free of 376 GB"
    assert (summary.pressure, summary.pressure_text) == (Pressure.WARNING, "High")
    assert summary.segments[0].legend == "Browser: 9.8 GB"
    assert summary.segments[4].legend == "Other: 950 MB"
    labels = {s.key: s.label for s in summary.segments}
    assert labels["kernel_cache"] == "System cache memory"
    assert labels["zram"] == "Compressed swap in RAM (zram)"
    assert summary.segments[-2].legend == "Unattributed: 1.9 GB"
    assert summary.segments[-1].legend == "Free: 13.7 GB"
    assert summary.kernel_cache_note == "The system's cache memory frees itself when needed."
    # The keys stay identities: they do not follow the language.
    assert [s.key for s in summary.segments[:2]] == ["BROWSER", "DESKTOP_APP"]


def test_status_follows_the_pressure_in_english(snapshot: Snapshot) -> None:
    ram_tight = roomy_disk(snapshot)
    warning = build_summary(snapshot=ram_tight)
    critical = build_summary(snapshot=replace(ram_tight, pressure=Pressure.CRITICAL))
    calm = build_summary(snapshot=replace(ram_tight, pressure=Pressure.OK))
    nothing = build_summary(
        snapshot=roomy_disk(
            replace(snapshot, reclaimable_now=replace(snapshot.reclaimable_now, ram=0))
        )
    )

    assert warning.status_title == "Memory is filling up"
    assert critical.status_title == "Memory is almost out"
    assert calm.status_title == "Your computer is doing fine"
    assert warning.status_text == (
        "You can free memory by closing programs you don't use. "
        "Nothing closes without your consent."
    )
    assert nothing.status_text == "There is nothing to close without risk."
    assert nothing.safe_label == ""


def test_status_names_the_disk_when_the_disk_drives_the_pressure_in_english(
    snapshot: Snapshot,
) -> None:
    warning = build_summary(snapshot=snapshot)
    critical = build_summary(snapshot=replace(snapshot, pressure=Pressure.CRITICAL))

    assert warning.status_title == "The disk is filling up"
    assert critical.status_title == "The disk is almost full"
    assert warning.status_text == (
        "Make room from the Disk tab: you'll find what can be deleted there."
    )


@pytest.mark.parametrize(
    ("sizes", "expected"),
    [
        ((9,), "Stop a: you're not using it and you lose nothing."),
        ((9, 5), "Stop a and b: you're not using them and you lose nothing."),
        ((9, 5, 3, 1), "Stop a, b, c and one more: you're not using them and you lose nothing."),
        (
            (9, 5, 3, 1, 1),
            "Stop a, b, c and 2 more: you're not using them and you lose nothing.",
        ),
    ],
)
def test_the_safe_button_names_the_programs_it_stops_in_english(
    snapshot: Snapshot, sizes: tuple[int, ...], expected: str
) -> None:
    groups = tuple(
        make_group(name, reclaimable=size)
        for name, size in zip("abcde"[: len(sizes)], sizes, strict=True)
    )
    shot = replace(
        with_groups(snapshot, *groups),
        reclaimable_now=replace(snapshot.reclaimable_now, ram=sum(sizes)),
    )

    summary = build_summary(snapshot=shot)

    assert summary.safe_label == f"Free {sum(sizes)} B of memory"
    assert summary.safe_text == expected
