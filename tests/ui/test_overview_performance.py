import math
import time
from datetime import datetime

import pytest
from gi.repository import GLib, Gtk

from tests.ui.conftest import make_group, with_groups
from wimm.model.snapshot import Snapshot
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.viewmodel import build_rows
from wimm.ui.views import RowFilters
from wimm.ui.widgets import install_style
from wimm.ui.widgets.group_row import GroupRowWidget

pytestmark = pytest.mark.ui
MANY_GROUPS = 300
BYTES_PER_UNIT = 1_000_000
# RNF-03: the main loop is never blocked for more than 50 ms.
SLICE_BUDGET_S = 0.050
# Reordering by remove+insert took 11-12 s here; the sorted list takes about 0.4 s.
MAPPED_REORDER_BUDGET_S = 3.0
SYNC_TIMEOUT_S = 30.0
JITTER = 0.03
SINE_STEP = 12.9898  # scatters the jitter without a random generator


def snapshot_of(base: Snapshot, values: list[int]) -> Snapshot:
    groups = (
        make_group(f"group-{i:03d}", reclaimable=value * BYTES_PER_UNIT)
        for i, value in enumerate(values)
    )
    return with_groups(base, *groups)


def visible_order(page: OverviewPage) -> list[str]:
    listing = next(iter(page.group_widgets.values())).get_parent()
    assert listing is not None
    order = []
    child = listing.get_first_child()
    while child is not None:
        # Section titles (P9) are list children too: only the rows carry an order.
        if isinstance(child, GroupRowWidget):
            order.append(child.group_id)
        else:
            assert isinstance(child, Gtk.Label)
        child = child.get_next_sibling()
    return order


def run_until_synced(page: OverviewPage) -> list[float]:
    """Drive the main loop one iteration at a time; return the duration of each."""
    context = GLib.MainContext.default()
    slices: list[float] = []
    deadline = time.monotonic() + SYNC_TIMEOUT_S
    while page.is_syncing or context.pending():
        assert time.monotonic() < deadline, "row sync did not finish"
        began = time.perf_counter()
        context.iteration(False)
        slices.append(time.perf_counter() - began)
    return slices


def show(page: OverviewPage, snapshot: Snapshot) -> list[float]:
    began = time.perf_counter()
    page.show_snapshot(snapshot=snapshot, now=snapshot.taken_at)
    return [time.perf_counter() - began, *run_until_synced(page)]


@pytest.fixture
def page(display: None) -> OverviewPage:
    install_style()
    return OverviewPage()


@pytest.fixture
def mapped_page(page: OverviewPage) -> OverviewPage:
    window = Gtk.Window(default_width=1000, default_height=700)
    window.set_child(page)
    window.present()
    run_until_synced(page)
    return page


@pytest.mark.perf
def test_reversed_update_of_three_hundred_groups_has_no_slice_over_the_budget(
    page: OverviewPage, snapshot: Snapshot
) -> None:
    values = [1000 + i for i in range(MANY_GROUPS)]
    show(page, snapshot_of(snapshot, values))

    slices = show(page, snapshot_of(snapshot, values[::-1]))

    worst = max(slices)
    print(f"\nreversed update, worst slice {worst * 1000:.0f} ms over {len(slices)} slices")
    assert worst < SLICE_BUDGET_S, f"worst slice {worst * 1000:.0f} ms, budget 50 ms"
    assert len(slices) > 1  # the work really was split


@pytest.mark.perf
def test_initial_build_of_three_hundred_groups_has_no_slice_over_the_budget(
    page: OverviewPage, snapshot: Snapshot
) -> None:
    slices = show(page, snapshot_of(snapshot, [1000 + i for i in range(MANY_GROUPS)]))

    worst = max(slices)
    print(f"\ninitial build, worst slice {worst * 1000:.0f} ms over {len(slices)} slices")
    assert len(page.group_widgets) == MANY_GROUPS
    assert worst < SLICE_BUDGET_S, f"worst slice {worst * 1000:.0f} ms, budget 50 ms"


@pytest.mark.perf
def test_reversed_update_in_a_mapped_window_does_not_reinsert_every_row(
    mapped_page: OverviewPage, snapshot: Snapshot
) -> None:
    values = [1000 + i for i in range(MANY_GROUPS)]
    show(mapped_page, snapshot_of(snapshot, values))

    began = time.perf_counter()
    slices = show(mapped_page, snapshot_of(snapshot, values[::-1]))
    total = time.perf_counter() - began

    worst = max(slices)
    print(f"\nmapped reversed update, total {total * 1000:.0f} ms, worst {worst * 1000:.0f} ms")
    assert total < MAPPED_REORDER_BUDGET_S, f"total {total:.1f} s, budget 3 s"
    assert worst < SLICE_BUDGET_S, f"worst slice {worst * 1000:.0f} ms, budget 50 ms"


def test_visible_order_matches_build_rows_after_reverse_and_jitter(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    values = [1000 + i for i in range(MANY_GROUPS)]
    jittered = [int(v * (1 + JITTER * math.sin(i * SINE_STEP))) for i, v in enumerate(values)]
    for step in (values, values[::-1], jittered):
        current = snapshot_of(snapshot, step)
        show(page, current)

        expected = [row.id for row in build_rows(snapshot=current, filters=RowFilters(), now=now)]
        assert visible_order(page) == expected
        assert len(expected) == MANY_GROUPS


def test_groups_added_and_removed_by_id_keep_the_order(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    show(page, snapshot_of(snapshot, [1000 + i for i in range(20)]))
    kept = page.group_widgets["id-group-005"]

    current = snapshot_of(snapshot, [500, 400, 300, 5000, 100, 9000])
    show(page, current)

    expected = [row.id for row in build_rows(snapshot=current, filters=RowFilters(), now=now)]
    assert visible_order(page) == expected
    assert page.group_widgets["id-group-005"] is kept
    assert "id-group-006" not in page.group_widgets


def test_expansion_is_preserved_when_the_order_changes(
    page: OverviewPage, snapshot: Snapshot
) -> None:
    values = [1000 + i for i in range(10)]
    show(page, snapshot_of(snapshot, values))
    widget = page.group_widgets["id-group-003"]
    widget.set_expanded(True)

    show(page, snapshot_of(snapshot, values[::-1]))

    assert page.group_widgets["id-group-003"] is widget
    assert widget.get_expanded()
    assert visible_order(page)[0] == "id-group-000"


def test_a_new_snapshot_during_a_sync_replaces_it_and_ends_ordered(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    values = [1000 + i for i in range(MANY_GROUPS)]
    page.show_snapshot(snapshot=snapshot_of(snapshot, values), now=now)
    assert page.is_syncing
    final = snapshot_of(snapshot, values[::-1])

    show(page, final)

    expected = [row.id for row in build_rows(snapshot=final, filters=RowFilters(), now=now)]
    assert visible_order(page) == expected
    assert not page.is_syncing
