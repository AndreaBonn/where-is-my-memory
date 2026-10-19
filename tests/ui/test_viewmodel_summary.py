from dataclasses import replace

import pytest

from tests.ui.viewmodel_helpers import FIXTURE, roomy_disk
from wimm.model.enums import Category, Pressure
from wimm.model.memory import MemoryBreakdown
from wimm.model.snapshot import (
    ProtectedSummaryItem,
    Snapshot,
)
from wimm.serialize import snapshot_from_json
from wimm.ui.disk_texts import DiskTotals
from wimm.ui.viewmodel import (
    build_summary,
    build_system_rows,
)


@pytest.fixture
def snapshot() -> Snapshot:
    return snapshot_from_json(text=FIXTURE.read_text())


def test_summary_formats_ram_swap_disk_and_reclaimable(snapshot: Snapshot) -> None:
    summary = build_summary(snapshot=snapshot)

    assert (summary.ram_used, summary.ram_total, summary.ram_available) == (
        "32,9 GB",
        "41,7 GB",
        "8,8 GB",
    )
    assert (summary.swap_used, summary.swap_total) == ("120 MB", "4,3 GB")
    assert (summary.disk_mount, summary.disk_used, summary.disk_total, summary.disk_free) == (
        "/",
        "329,6 GB",
        "375,8 GB",
        "27,9 GB",
    )
    disk = DiskTotals(safe=7_400_000_000, review=0)
    assert build_summary(snapshot=snapshot, disk_totals=disk).disk_safe_label == (
        "Libera 7,4 GB di disco"
    )
    assert (summary.pressure, summary.pressure_text) == (Pressure.WARNING, "Alta")
    assert summary.ram_fraction == pytest.approx(32.9 / 41.742)
    assert summary.disk_fraction == pytest.approx(329638211584 / 375809638400)
    assert "si libera da sola" in summary.kernel_cache_note


def test_summary_headlines_use_round_numbers_and_plain_words(snapshot: Snapshot) -> None:
    summary = build_summary(snapshot=snapshot)

    assert summary.ram_headline == "33 GB usati su 42 GB"
    # In the fixture the disk (7% free) drives the pressure, not the RAM (21% free).
    assert summary.ram_details == "disponibili 8,8 GB · swap 120 MB su 4,3 GB"
    ram_tight = build_summary(snapshot=roomy_disk(snapshot))
    assert (
        ram_tight.ram_details == "disponibili 8,8 GB · swap 120 MB su 4,3 GB · memoria quasi piena"
    )
    calm = build_summary(snapshot=replace(snapshot, pressure=Pressure.OK))
    assert calm.ram_details == "disponibili 8,8 GB · swap 120 MB su 4,3 GB"
    assert summary.disk_headline == "28 GB liberi su 376 GB"


def test_summary_segments_are_ranked_and_carry_a_text_legend(snapshot: Snapshot) -> None:
    segments = build_summary(snapshot=snapshot).segments

    assert [s.key for s in segments] == [
        "BROWSER",
        "DESKTOP_APP",
        "AI_CLI",
        "DEV_SERVER",
        "other_programs",
        "kernel_cache",
        "shared_tmpfs",
        "kernel_unreclaimable",
        "zram",
        "unattributed",
        "free",
    ]
    assert segments[0].legend == "Browser: 9,8 GB"
    assert segments[4].legend == "Altro: 950 MB"
    assert segments[-2].legend == "Non attribuita: 1,9 GB"
    assert segments[5].label == "Memoria di appoggio del sistema"
    # zswap is 0 in the fixture, so it has no segment at all.
    assert "zswap" not in {s.key for s in segments}
    assert segments[-1].legend == "Libera: 13,7 GB"
    assert segments[0].fraction == pytest.approx(9.8 / 41.742)


def test_summary_segments_cover_total_memory_and_percents_sum_to_100(
    snapshot: Snapshot,
) -> None:
    segments = build_summary(snapshot=snapshot).segments

    assert sum(s.size for s in segments) == snapshot.memory.total
    assert sum(s.percent for s in segments) == 100
    assert sum(s.fraction for s in segments) == pytest.approx(1.0)


def test_percents_sum_to_100_when_plain_rounding_would_not(snapshot: Snapshot) -> None:
    thirds = MemoryBreakdown(
        categories=((Category.BROWSER, 1), (Category.CONTAINER, 1)), kernel_cache=0, unattributed=1
    )
    memory = replace(snapshot.memory, total=3, used=3, available=0, breakdown=thirds)

    segments = build_summary(snapshot=replace(snapshot, memory=memory)).segments

    assert [s.percent for s in segments if s.size] == [34, 33, 33]
    assert sum(s.percent for s in segments) == 100


def test_summary_always_lists_unattributed_but_skips_empty_categories(snapshot: Snapshot) -> None:
    empty = MemoryBreakdown(
        categories=((Category.BROWSER, 0), (Category.CONTAINER, 5)), kernel_cache=0, unattributed=0
    )
    shot = replace(snapshot, memory=replace(snapshot.memory, breakdown=empty))

    segments = build_summary(snapshot=shot).segments

    assert [s.key for s in segments] == ["CONTAINER", "unattributed", "free"]
    assert segments[1].legend == "Non attribuita: 0 B"


def test_summary_without_free_memory_has_no_free_segment(snapshot: Snapshot) -> None:
    full = MemoryBreakdown(categories=((Category.BROWSER, 10),), kernel_cache=0, unattributed=0)
    memory = replace(snapshot.memory, total=10, used=10, available=0, breakdown=full)

    segments = build_summary(snapshot=replace(snapshot, memory=memory)).segments

    assert [s.key for s in segments] == ["BROWSER", "unattributed"]
    assert segments[0].percent == 100


def test_summary_with_zero_totals_has_zero_fractions(snapshot: Snapshot) -> None:
    memory = replace(
        snapshot.memory,
        total=0,
        used=0,
        available=0,
        breakdown=MemoryBreakdown(categories=(), kernel_cache=0, unattributed=0),
    )
    shot = replace(snapshot, memory=memory, disk=replace(snapshot.disk, total=0, used=0, free=0))

    summary = build_summary(snapshot=shot)

    assert (summary.ram_fraction, summary.disk_fraction) == (0.0, 0.0)


def test_system_rows_are_read_only_and_largest_first(snapshot: Snapshot) -> None:
    extra = (
        ProtectedSummaryItem(label="Audio", memory=300_000_000, reason="servizio di sistema"),
        ProtectedSummaryItem(label="Altri utenti", memory=300_000_000, reason="processi di altri"),
    )
    shot = replace(snapshot, protected_summary=snapshot.protected_summary + extra)

    rows = build_system_rows(snapshot=shot)

    assert [(r.label, r.memory, r.reason) for r in rows] == [
        ("Sessione GNOME", "1,4 GB", "componente del desktop"),
        ("Altri utenti", "300 MB", "processi di altri"),
        ("Audio", "300 MB", "servizio di sistema"),
    ]
    assert not hasattr(rows[0], "primary_action")
