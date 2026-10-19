"""The top of the Panoramica: one amount freed without losing anything, and how (P-hero)."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.ui.viewmodel_helpers import make_group, with_groups
from wimm.model.enums import Risk
from wimm.model.snapshot import Snapshot
from wimm.serialize import snapshot_from_json
from wimm.ui.disk_texts import DiskTotals
from wimm.ui.summary_reclaim import reclaim_fields

FIXTURE = Path(__file__).parents[1] / "fixtures" / "snapshot_whitebox.json"
MB = 1_000_000


@pytest.fixture
def idle_safe() -> Snapshot:
    """Two idle safe groups behind 22 MB of safely reclaimable memory."""
    base = snapshot_from_json(text=FIXTURE.read_text())
    groups = (
        make_group("gitstatusd", reclaimable=13 * MB),
        make_group("sigv4", reclaimable=9 * MB),
    )
    shot = with_groups(base, *groups)
    return replace(shot, reclaimable_now=replace(shot.reclaimable_now, ram=22 * MB))


def test_memory_and_safe_disk_add_up_to_one_amount(idle_safe: Snapshot) -> None:
    fields = reclaim_fields(snapshot=idle_safe, disk=DiskTotals(safe=5_000 * MB, review=6_600 * MB))

    assert fields["reclaim_headline"] == "Puoi liberare 5,0 GB senza perdere niente"
    assert fields["reclaim_details"] == "22 MB di memoria · 5,0 GB di disco"
    assert fields["safe_label"] == "Libera 22 MB di memoria"
    assert fields["disk_safe_label"] == "Libera 5,0 GB di disco"
    assert fields["review_text"] == "Altri 6,6 GB se accetti di riscaricare o ricostruire"


def test_before_the_disk_scan_the_disk_is_unchecked_not_zero(idle_safe: Snapshot) -> None:
    fields = reclaim_fields(snapshot=idle_safe, disk=None)

    assert fields["reclaim_headline"] == "Puoi liberare 22 MB senza perdere niente"
    assert fields["reclaim_details"] == (
        "Il disco non è ancora stato controllato: per ora conta solo la memoria."
    )
    assert "0 B" not in fields["reclaim_details"]
    assert fields["disk_safe_label"] == ""
    assert fields["review_text"] == ""


def test_memory_no_safe_group_stands_behind_is_not_counted(idle_safe: Snapshot) -> None:
    risky = with_groups(idle_safe, make_group("firefox", reclaimable=22 * MB, risk=Risk.CAUTION))

    fields = reclaim_fields(snapshot=risky, disk=DiskTotals(safe=3 * MB, review=0))

    assert fields["reclaim_headline"] == "Puoi liberare 3 MB senza perdere niente"
    assert fields["reclaim_details"] == "3 MB di disco"
    assert fields["safe_label"] == ""


def test_with_nothing_safe_anywhere_the_headline_says_so(idle_safe: Snapshot) -> None:
    empty = with_groups(idle_safe)

    fields = reclaim_fields(snapshot=empty, disk=DiskTotals(safe=0, review=2 * MB))

    assert fields["reclaim_headline"] == "Niente da liberare senza perdere qualcosa"
    assert fields["reclaim_details"] == ""
    assert (fields["safe_label"], fields["disk_safe_label"]) == ("", "")
    assert fields["review_text"] == "2 MB si liberano se accetti di riscaricare o ricostruire"


def test_with_no_safe_memory_and_an_unchecked_disk_nothing_is_claimed_for_the_disk(
    idle_safe: Snapshot,
) -> None:
    fields = reclaim_fields(snapshot=with_groups(idle_safe), disk=None)

    assert fields["reclaim_headline"] == "Niente da liberare in memoria senza perdere qualcosa"
    assert fields["reclaim_details"].startswith("Il disco non è ancora stato controllato")
