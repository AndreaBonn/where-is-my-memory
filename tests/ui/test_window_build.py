import time
from dataclasses import replace

import pytest
from gi.repository import Gio, GLib, Gtk

from tests.ui.conftest import (
    FakeSource,
    WindowFactory,
    all_filter,
    descendants,
    idle_filter,
    make_group,
    present_and_settle,
    settle,
    with_groups,
)
from wimm.model.enums import ActivityState, Category
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets.group_row import PRIMARY_ACTION_NAME, GroupRowWidget
from wimm.ui.window_state import DEFAULT_HEIGHT, DEFAULT_WIDTH, MIN_HEIGHT, MIN_WIDTH

pytestmark = pytest.mark.ui
MANY_GROUPS = 300
LONG_NAME = "x" * 200
IDLE_MESSAGE = "Niente da liberare: il resto è in uso o ancora in osservazione."
BUILD_BUDGET_S = 1.0
# RNF-03: no main-loop slice of row work may exceed 50 ms.
SLICE_BUDGET_S = 0.050
ALL_ROWS_TIMEOUT_S = 30.0


def primary_buttons(widget: Gtk.Widget) -> list[Gtk.Widget]:
    return [w for w in descendants(widget) if w.get_name() == PRIMARY_ACTION_NAME]


def test_window_builds_from_the_fixture_snapshot(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))

    assert window.overview.visible_state == "content"
    assert list(window.overview.group_widgets) == ["g_3f9a1c"]
    assert window.overview.group_widgets["g_3f9a1c"].get_title() == "whitebox"
    assert window.get_default_size() == (DEFAULT_WIDTH, DEFAULT_HEIGHT)
    assert window.get_size_request() == (MIN_WIDTH, MIN_HEIGHT)


def test_close_request_returns_true_and_the_window_stays_hidden_but_alive(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)
    assert window.get_visible()

    handled = window.emit("close-request")

    assert handled is True
    assert not window.get_visible()
    window.present()
    assert window.get_visible()


def test_window_is_not_attached_to_an_application_but_sees_its_actions(
    window_factory: WindowFactory, snapshot: Snapshot, application: Gio.Application
) -> None:
    activated: list[str] = []
    action = Gio.SimpleAction.new("probe", None)
    action.connect("activate", lambda *_a: activated.append("probe"))
    application.add_action(action)
    window = window_factory(FakeSource(snapshot=snapshot))

    assert window.get_application() is None
    window.activate_action("app.probe", None)
    assert activated == ["probe"]
    assert window.activate_action("app.missing", None) is False


def test_protected_group_is_absent_and_actionable_group_has_one_button(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    (actionable,) = snapshot.groups
    protected = make_group("gnome-shell", category=Category.SESSION, risk=None)
    window = window_factory(FakeSource(snapshot=with_groups(snapshot, actionable, protected)))

    assert "id-gnome-shell" not in window.overview.group_widgets
    assert len(primary_buttons(window.overview)) == 1
    assert window.system.row_count == 1


@pytest.mark.perf
def test_three_hundred_groups_build_in_slices_and_end_in_viewmodel_order(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    groups = tuple(make_group(f"group-{i:03d}", reclaimable=1000 + i) for i in range(MANY_GROUPS))
    source = FakeSource(snapshot=with_groups(snapshot, *groups))

    started = time.perf_counter()
    window = window_factory(source, settled=False)
    slices = [time.perf_counter() - started]
    deadline = time.monotonic() + ALL_ROWS_TIMEOUT_S
    context = GLib.MainContext.default()
    while len(window.overview.group_widgets) < MANY_GROUPS or window.overview.is_syncing:
        assert time.monotonic() < deadline, f"{len(window.overview.group_widgets)} rows built"
        began = time.perf_counter()
        context.iteration(False)
        slices.append(time.perf_counter() - began)
    print(f"\nbuild of {MANY_GROUPS} groups: worst slice {max(slices) * 1000:.0f} ms")

    listing = window.overview.group_widgets["id-group-000"].get_parent()
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
    assert order == [f"id-group-{i:03d}" for i in reversed(range(MANY_GROUPS))]
    assert len(primary_buttons(window.overview)) == MANY_GROUPS
    assert max(slices) < SLICE_BUDGET_S, f"worst slice {max(slices) * 1000:.0f} ms"


@pytest.mark.perf
def test_three_hundred_group_update_only_touches_changed_rows(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    groups = tuple(make_group(f"group-{i:03d}", reclaimable=1000 + i) for i in range(MANY_GROUPS))
    source = FakeSource(snapshot=with_groups(snapshot, *groups))
    window = window_factory(source)
    present_and_settle(window)
    changed = (make_group("group-000", reclaimable=9_000_000), *groups[1:])

    started = time.perf_counter()
    source.publish(with_groups(snapshot, *changed))
    elapsed = time.perf_counter() - started
    settle(window_or_page=window)
    print(f"\nupdate of {MANY_GROUPS} groups, 1 changed: {elapsed * 1000:.0f} ms")

    first = window.overview.group_widgets["id-group-000"]
    listing = first.get_parent()
    assert listing is not None
    assert listing.get_first_child() is first
    assert elapsed < BUILD_BUDGET_S


def test_a_two_hundred_character_name_is_ellipsized_in_the_window(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=with_groups(snapshot, make_group(LONG_NAME))))

    labels = [w for w in descendants(window.overview) if isinstance(w, Gtk.Label)]
    (title,) = [label for label in labels if label.get_label() == LONG_NAME]

    assert title.get_ellipsize().value_nick == "end"


def test_the_list_opens_on_what_can_be_freed_and_tutto_shows_the_rest(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    idle = make_group("idle-one")
    busy = make_group("busy-one", state=ActivityState.ACTIVE)
    window = window_factory(FakeSource(snapshot=with_groups(snapshot, idle, busy)))
    assert idle_filter(window.overview).get_active()
    assert idle_filter(window.overview).get_label() == "Da liberare (1)"
    assert set(window.overview.group_widgets) == {"id-idle-one"}

    all_filter(window.overview).set_active(True)
    settle(window_or_page=window)

    assert all_filter(window.overview).get_label() == "Tutto (2)"
    assert set(window.overview.group_widgets) == {"id-idle-one", "id-busy-one"}


def test_empty_state_shows_the_verbatim_text_when_nothing_is_idle(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    busy = make_group("busy-one", state=ActivityState.ACTIVE)
    window = window_factory(FakeSource(snapshot=with_groups(snapshot, busy)))

    idle_filter(window.overview).set_active(True)
    settle(window_or_page=window)

    titles = {w.get_title() for w in descendants(window.overview) if hasattr(w, "get_title")}
    assert IDLE_MESSAGE in titles
    assert not window.overview.group_widgets


def header_text(widget: Gtk.ListBoxRow) -> str | None:
    header = widget.get_header()
    return header.get_label() if isinstance(header, Gtk.Label) else None


def test_section_titles_mark_where_idle_and_in_use_rows_start(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    idle = make_group("idle-one", reclaimable=10)
    busy = make_group("busy-one", reclaimable=900, state=ActivityState.ACTIVE)
    source = FakeSource(snapshot=with_groups(snapshot, idle, busy))
    window = window_factory(source)
    present_and_settle(window)
    all_filter(window.overview).set_active(True)
    settle(window_or_page=window)
    rows = window.overview.group_widgets

    assert header_text(rows["id-idle-one"]) == "Da liberare · non li usi da tempo"
    assert header_text(rows["id-busy-one"]) == "In uso adesso o non misurabile"

    source.publish(with_groups(snapshot, replace(idle, activity=busy.activity), busy))
    present_and_settle(window)

    titles = [header_text(rows[gid]) for gid in ("id-busy-one", "id-idle-one")]
    assert titles == ["In uso adesso o non misurabile", None]
