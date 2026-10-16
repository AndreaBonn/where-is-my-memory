import logging
from dataclasses import replace
from datetime import datetime

import pytest
from gi.repository import Adw, GLib, Gtk

from tests.ui.conftest import (
    FakeSource,
    WindowFactory,
    descendants,
    idle_filter,
    make_group,
    with_groups,
)
from tests.ui.test_overview_performance import (
    MANY_GROUPS,
    run_until_synced,
    show,
    snapshot_of,
    visible_order,
)
from wimm.model.enums import ActivityState
from wimm.model.snapshot import ProcessMember, Snapshot
from wimm.ui.pages import overview as overview_module
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.viewmodel import build_rows
from wimm.ui.widgets import install_style

pytestmark = pytest.mark.ui
FIRST_SLICE_BUDGET_S = 10.0
SETTLE_ITERATIONS = 20
HOUR_S = 3600
FOCUS_SCROLL = 15_000.0


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


def partial_sync(page: OverviewPage, snapshot: Snapshot, now: datetime) -> None:
    """Start a sync of the snapshot and stop it while it is half way."""
    page.show_snapshot(snapshot=snapshot, now=now)
    assert page.is_syncing
    assert 0 < len(page.group_widgets) < MANY_GROUPS


def source_alive(source_id: int) -> bool:
    return GLib.MainContext.default().find_source_by_id(source_id) is not None


def test_show_group_at_the_bottom_during_a_sync_keeps_the_row_in_view(
    mapped_page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    values = [1000 + i for i in range(MANY_GROUPS)]
    show(mapped_page, snapshot_of(snapshot, values))
    adjustment = mapped_page._scroller.get_vadjustment()
    assert adjustment.get_value() == 0
    changed = [value + 1 for value in values]
    mapped_page.show_snapshot(snapshot=snapshot_of(snapshot, changed), now=now)
    assert mapped_page.is_syncing

    assert mapped_page.expand_group(group_id="id-group-000")
    # Under xvfb (no window manager) the focus does not scroll, so the scroll to the
    # focused row is applied by hand, right where grab_focus would have done it.
    adjustment.set_value(FOCUS_SCROLL)
    run_until_synced(mapped_page)
    for _ in range(SETTLE_ITERATIONS):
        GLib.MainContext.default().iteration(False)

    assert adjustment.get_value() == FOCUS_SCROLL


def test_cancel_removes_the_sync_idle_and_stops_syncing(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    partial_sync(page, snapshot_of(snapshot, list(range(MANY_GROUPS))), now)
    sync_id = page._job_source
    assert source_alive(sync_id)

    page.cancel()

    assert not page.is_syncing
    assert not source_alive(sync_id)


def test_cancel_removes_the_pending_scroll_restore(
    page: OverviewPage, snapshot: Snapshot, now: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A generous first slice: under load the real budget can end it before three rows are built.
    monkeypatch.setattr("wimm.ui.pages.overview.SLICE_BUDGET_S", FIRST_SLICE_BUDGET_S)
    page.show_snapshot(snapshot=snapshot_of(snapshot, [1, 2, 3]), now=now)
    assert not page.is_syncing
    restore_id = page._restore_source
    assert restore_id
    assert source_alive(restore_id)

    page.cancel()

    assert not source_alive(restore_id)


def test_destroying_the_window_leaves_no_idle_of_the_page(
    window_factory: WindowFactory, snapshot: Snapshot, now: datetime
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.overview.show_snapshot(snapshot=snapshot_of(snapshot, list(range(MANY_GROUPS))), now=now)
    assert window.overview.is_syncing
    sync_id = window.overview._job_source
    assert source_alive(sync_id)

    window.destroy()

    assert not source_alive(sync_id)
    assert not window.overview.is_syncing


class ExplodingRow(Adw.ExpanderRow):
    def __init__(self, *, row: object) -> None:
        raise RuntimeError("cannot build row")


def test_a_failing_row_build_ends_the_sync_and_logs_the_traceback(
    page: OverviewPage,
    snapshot: Snapshot,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(overview_module, "GroupRowWidget", ExplodingRow)

    with caplog.at_level(logging.ERROR, logger=overview_module.LOGGER.name):
        page.show_snapshot(snapshot=snapshot_of(snapshot, [1, 2]), now=now)

    assert not page.is_syncing
    (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError

    monkeypatch.undo()
    show(page, snapshot_of(snapshot, [1, 2]))
    assert len(page.group_widgets) == 2


def test_a_snapshot_with_other_ids_mid_slicing_leaves_only_the_new_ids(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    partial_sync(page, snapshot_of(snapshot, list(range(MANY_GROUPS))), now)
    groups = (make_group(f"new-{i:02d}", reclaimable=1000 + i) for i in range(12))
    current = with_groups(snapshot, *groups)

    show(page, current)

    expected = [
        row.id for row in build_rows(snapshot=current, filters=page._filters.filters, now=now)
    ]
    assert len(expected) == 12
    assert set(page.group_widgets) == set(expected)
    assert visible_order(page) == expected
    assert not page.is_syncing


def test_a_filter_change_mid_slicing_shows_only_the_matching_groups(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    groups = (
        make_group(
            f"g-{i:03d}",
            reclaimable=1000 + i,
            state=ActivityState.IDLE if i % 2 else ActivityState.ACTIVE,
        )
        for i in range(MANY_GROUPS)
    )
    current = with_groups(snapshot, *groups)
    partial_sync(page, current, now)

    idle_filter(page).set_active(True)
    run_until_synced(page)

    expected = [
        row.id for row in build_rows(snapshot=current, filters=page._filters.filters, now=now)
    ]
    assert len(expected) == MANY_GROUPS // 2
    assert set(page.group_widgets) == set(expected)
    assert visible_order(page) == expected


def test_expand_group_while_syncing_builds_the_row_and_expands_it(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    partial_sync(page, snapshot_of(snapshot, list(range(MANY_GROUPS))), now)
    assert "id-group-000" not in page.group_widgets

    assert page.expand_group(group_id="id-group-000")

    assert not page.is_syncing
    assert len(page.group_widgets) == MANY_GROUPS
    assert page.group_widgets["id-group-000"].get_expanded()


def test_a_reused_pid_updates_the_member_row_in_place(
    page: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    process = next(m for g in snapshot.groups for m in g.members if isinstance(m, ProcessMember))
    group = replace(snapshot.groups[0], members=(process,))
    show(page, with_groups(snapshot, group))
    widget = page.group_widgets[group.id]
    widget.set_expanded(True)
    before = member_row(widget, process.name)
    old_started = (
        build_rows(snapshot=with_groups(snapshot, group), filters=page._filters.filters, now=now)[0]
        .members[0]
        .started
    )

    reused = replace(
        process,
        create_time=process.create_time + HOUR_S,
        name="reused",
        cmdline=("reused", "--new"),
    )
    current = with_groups(snapshot, replace(group, members=(reused,)))
    show(page, current)

    new_member = build_rows(snapshot=current, filters=page._filters.filters, now=now)[0].members[0]
    assert new_member.started is not None
    assert new_member.started != old_started
    after = member_row(widget, "reused")
    assert after is before
    assert new_member.started in (after.get_subtitle() or "")
    assert old_started is not None
    assert old_started not in (after.get_subtitle() or "")


def member_row(widget: Adw.ExpanderRow, title: str) -> Adw.ActionRow:
    (row,) = [
        w for w in descendants(widget) if isinstance(w, Adw.ActionRow) and w.get_title() == title
    ]
    return row
