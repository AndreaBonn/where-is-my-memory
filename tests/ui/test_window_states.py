from datetime import datetime

import pytest
from gi.repository import Gio, GObject, Gtk

from tests.ui.conftest import (
    FakeSource,
    WindowFactory,
    descendants,
    idle_filter,
    make_group,
    present_and_settle,
    settle,
    wait_until,
    with_groups,
)
from wimm.model.enums import ActivityState
from wimm.model.snapshot import Snapshot
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.widgets.group_row import GroupRowWidget

pytestmark = pytest.mark.ui
# Shorter than FAILURE_POLL_SECONDS: only the immediate poll on map can satisfy it.
FAST_WAIT_S = 1.0


def test_error_state_appears_at_three_failures_and_not_at_two(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    two = window_factory(FakeSource(snapshot=snapshot, failures=2))
    three = window_factory(FakeSource(snapshot=snapshot, failures=3))

    assert two.overview.visible_state == "content"
    assert three.overview.visible_state == "error"
    titles = [w.get_title() for w in descendants(three.overview) if hasattr(w, "get_title")]
    assert "Non riesco a leggere i dati del computer" in titles


def test_restart_button_is_enabled_only_when_the_app_action_exists(
    window_factory: WindowFactory, snapshot: Snapshot, application: Gio.Application
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot, failures=3))
    present_and_settle(window)
    (button,) = [
        w
        for w in descendants(window.overview)
        if isinstance(w, Gtk.Button) and w.get_label() == "Riprova adesso"
    ]
    assert not button.get_sensitive()

    application.add_action(Gio.SimpleAction.new("restart-monitor", None))
    wait_until(button.get_sensitive, description="restart button enabled by the app action")


def test_loading_shows_the_slow_text_after_the_timeout(display: None) -> None:
    page = OverviewPage(slow_loading_ms=30)
    assert page.visible_state == "loading"
    assert not any(slow_texts(page))

    wait_until(
        lambda: "Ci sta mettendo più del previsto" in slow_texts(page),
        description="slow loading text",
    )


def test_snapshot_arriving_cancels_the_slow_loading_text(
    display: None, snapshot: Snapshot, now: datetime
) -> None:
    page = OverviewPage(slow_loading_ms=30)

    page.show_snapshot(snapshot=snapshot, now=now)
    settle(window_or_page=page)

    # The timer source is gone, so the text cannot appear later; the test above pins the positive.
    assert page._slow_timer == 0
    assert "Ci sta mettendo più del previsto" not in slow_texts(page)
    assert page.visible_state == "content"


def test_window_without_data_shows_loading_then_content(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    source = FakeSource(snapshot=None)
    window = window_factory(source)
    present_and_settle(window)
    assert window.overview.visible_state == "loading"

    source.publish(snapshot)
    settle(window_or_page=window)

    assert window.overview.visible_state == "content"


def test_show_group_presents_the_window_and_expands_the_group(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    widget = window.overview.group_widgets["g_3f9a1c"]
    assert not widget.get_expanded()

    window.show_group("g_3f9a1c")

    assert window.get_visible()
    assert widget.get_expanded()


def test_show_group_clears_a_filter_that_hides_the_group(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    busy = make_group("busy-one", state=ActivityState.ACTIVE)
    window = window_factory(FakeSource(snapshot=with_groups(snapshot, busy)))
    idle_filter(window.overview).set_active(True)
    settle(window_or_page=window)
    assert not window.overview.group_widgets

    window.show_group("id-busy-one")
    settle(window_or_page=window)

    assert window.overview.group_widgets["id-busy-one"].get_expanded()


def test_show_group_none_only_presents(window_factory: WindowFactory, snapshot: Snapshot) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))

    window.show_group(None)

    assert window.get_visible()
    assert not window.overview.group_widgets["g_3f9a1c"].get_expanded()


def test_update_keeps_expanded_rows_the_filter_and_the_other_rows(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    keep = make_group("keep-me", reclaimable=500)
    other = make_group("other", reclaimable=100)
    source = FakeSource(snapshot=with_groups(snapshot, keep, other))
    window = window_factory(source)
    present_and_settle(window)
    window.overview.group_widgets["id-keep-me"].set_expanded(True)
    idle_filter(window.overview).set_active(True)
    settle(window_or_page=window)
    before = window.overview.group_widgets["id-keep-me"]

    source.publish(with_groups(snapshot, make_group("keep-me", reclaimable=900), other))
    settle(window_or_page=window)

    after = window.overview.group_widgets["id-keep-me"]
    assert after is before
    assert after.get_expanded()
    assert idle_filter(window.overview).get_active()
    assert after.get_subtitle() is not None
    assert list(window.overview.group_widgets) == ["id-keep-me", "id-other"]


def test_update_reorders_rows_by_reclaimable_memory(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    a, b = make_group("a", reclaimable=500), make_group("b", reclaimable=100)
    source = FakeSource(snapshot=with_groups(snapshot, a, b))
    window = window_factory(source)
    present_and_settle(window)

    source.publish(with_groups(snapshot, make_group("a", reclaimable=50), b))
    settle(window_or_page=window)

    ordered = [w.group_id for w in descendants(window.overview) if isinstance(w, GroupRowWidget)]
    assert ordered == ["id-b", "id-a"]


def test_hidden_window_defers_the_rebuild_until_it_is_shown(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    source = FakeSource(snapshot=snapshot)
    window = window_factory(source)

    source.publish(with_groups(snapshot, make_group("late")))
    assert list(window.overview.group_widgets) == ["g_3f9a1c"]

    window.show_group(None)
    settle(window_or_page=window)

    assert list(window.overview.group_widgets) == ["id-late"]


def test_failures_are_noticed_while_visible_even_without_a_signal(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    source = FakeSource(snapshot=snapshot)
    window = window_factory(source)
    present_and_settle(window)

    source.consecutive_failures = 3
    window._poll_failures()

    assert window.overview.visible_state == "error"


def test_reopening_after_accumulated_failures_shows_the_error_at_once(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    source = FakeSource(snapshot=snapshot)
    window = window_factory(source)
    present_and_settle(window)
    window.emit("close-request")
    wait_until(lambda: not window.get_visible(), description="window hidden")
    source.consecutive_failures = 3
    assert window.overview.visible_state == "content"

    window.present()
    wait_until(
        lambda: window.overview.visible_state == "error",
        description="error state before the first poll",
        timeout_s=FAST_WAIT_S,
    )


def slow_texts(page: OverviewPage) -> list[str]:
    return [w.get_description() for w in descendants(page) if hasattr(w, "get_description")]


def has_update_handler(source: FakeSource) -> bool:
    signal_id = GObject.signal_lookup("snapshot-updated", source)
    return GObject.signal_has_handler_pending(source, signal_id, 0, False)


def test_destroyed_window_disconnects_from_the_long_lived_source(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    source = FakeSource(snapshot=snapshot)
    window = window_factory(source)
    assert has_update_handler(source)

    window.destroy()

    assert not has_update_handler(source)
