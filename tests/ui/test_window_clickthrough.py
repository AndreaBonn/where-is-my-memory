import pytest
from gi.repository import Adw, Gdk, Gtk

from tests.ui.conftest import (
    FakeSource,
    RefreshableSource,
    WindowFactory,
    descendants,
    focus_is_in,
    idle_filter,
    present_and_settle,
    settle,
    wait_until,
)
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets.group_row import GroupRowWidget

pytestmark = pytest.mark.ui
GROUP_ID = "g_3f9a1c"
CLIPBOARD_TIMEOUT_S = 2.0


def press(window: Gtk.Window, trigger: str) -> bool:
    """Run the window shortcut bound to ``trigger`` (Xvfb has no window manager)."""
    controllers = window.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if not isinstance(controller, Gtk.ShortcutController):
            continue
        for shortcut in controller:
            if not isinstance(shortcut, Gtk.Shortcut):
                continue
            bound = shortcut.get_trigger()
            if bound is not None and bound.to_string() == trigger:
                action = shortcut.get_action()
                assert action is not None
                return bool(action.activate(Gtk.ShortcutActionFlags.EXCLUSIVE, window, None))
    raise AssertionError(f"no shortcut {trigger}")


def read_clipboard(widget: Gtk.Widget) -> str | None:
    result: list[str | None] = []
    clipboard: Gdk.Clipboard = widget.get_clipboard()
    clipboard.read_text_async(None, lambda c, r: result.append(c.read_text_finish(r)))
    wait_until(lambda: bool(result), description="clipboard text", timeout_s=CLIPBOARD_TIMEOUT_S)
    return result[0]


def test_ctrl_f_puts_the_focus_on_the_search_entry(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    search = window.overview._filters.search
    assert press(window, "<Control>f")
    wait_until(lambda: focus_is_in(window, search), description="focus on search")

    focus = window.get_focus()
    assert focus is not None
    assert focus is search or focus.is_ancestor(search)


def test_f5_asks_for_a_sample_only_when_the_source_can(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    capable = RefreshableSource(snapshot=snapshot)
    window = window_factory(capable)
    plain = window_factory(FakeSource(snapshot=snapshot))

    press(window, "F5")
    press(plain, "F5")

    assert capable.refreshes == 1


def test_expanding_a_row_shows_its_members_and_filtering_idle_reduces_rows(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)
    row = window.overview.group_widgets[GROUP_ID]
    before = len(window.overview.group_widgets)

    row.set_expanded(True)
    members = [w for w in descendants(row) if isinstance(w, Adw.ActionRow)]
    wait_until(lambda: all(w.get_mapped() for w in members), description="members mapped")
    idle_filter(window.overview).set_active(True)
    wait_until(lambda: not window.overview.is_syncing, description="filtered rows built")

    assert len(members) >= 3
    assert 0 < len(window.overview.group_widgets) <= before


def test_copy_pid_from_the_member_menu_fills_the_clipboard(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)
    row: GroupRowWidget = window.overview.group_widgets[GROUP_ID]
    row.set_expanded(True)
    wait_until(lambda: row.get_expanded(), description="row expanded")
    settle(window_or_page=window)
    uvicorn = next(
        w for w in descendants(row) if isinstance(w, Adw.ActionRow) and w.get_title() == "uvicorn"
    )

    assert uvicorn.activate_action("ctx.copy-pid", None)

    assert read_clipboard(uvicorn) == "941149"


def test_closing_hides_the_window_without_destroying_it(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    window.emit("close-request")
    wait_until(lambda: not window.get_visible(), description="window hidden")

    assert not window.get_visible()
