"""The window chrome, filter bar, state views, group rows and the disk header in English."""

from datetime import datetime
from typing import cast

import pytest
from gi.repository import Adw, Gio, Gtk

from tests.ui.conftest import (
    FakeActionService,
    FakeSource,
    RefreshableSource,
    WindowFactory,
    descendants,
    present_and_settle,
)
from tests.ui.fakes import FakeDiskSource
from tests.ui.test_group_controls import one_group, open_group
from wimm.model.snapshot import Snapshot
from wimm.ui.widgets.state_views import ErrorView, LoadingView, failure_cause
from wimm.ui.window_notify import build_main_menu

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("english")]


def _texts(widget: Gtk.Widget) -> list[str]:
    """Every text a widget tree shows: labels, button labels, row titles and subtitles."""
    found: list[str] = []
    for item in descendants(widget):
        if isinstance(item, Gtk.Label):
            found.append(item.get_text())
        elif isinstance(item, Gtk.Button | Gtk.ToggleButton | Gtk.MenuButton | Gtk.CheckButton):
            found.append(item.get_label() or "")
        if isinstance(item, Adw.PreferencesRow | Adw.ActionRow):
            found.append(item.get_title() or "")
    return found


def _menu_labels(menu: Gio.MenuModel | None) -> list[str]:
    assert menu is not None
    labels = []
    for index in range(menu.get_n_items()):
        value = menu.get_item_attribute_value(index, "label", None)
        assert value is not None
        labels.append(value.get_string())
    return labels


def test_the_view_switcher_pages_are_titled_in_english(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))

    pages = cast(Gio.ListModel, window.view_stack.get_pages())
    items = [cast(Adw.ViewStackPage, pages.get_item(i)) for i in range(pages.get_n_items())]
    titles = [item.get_title() for item in items]

    assert titles == ["Overview", "Disk"]


def test_the_main_menu_and_the_header_buttons_are_english(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(RefreshableSource(snapshot=snapshot))

    menu_button = next(
        w
        for w in descendants(window)
        if isinstance(w, Gtk.MenuButton) and w.get_icon_name() == "open-menu-symbolic"
    )
    refresh = next(
        w
        for w in descendants(window)
        if isinstance(w, Gtk.Button) and w.get_action_name() == "win.refresh"
    )

    assert _menu_labels(menu_button.get_menu_model()) == [
        "Preferences",
        "Mute for 1 h",
        "About",
        "Quit",
    ]
    assert menu_button.get_tooltip_text() == "Main menu"
    assert refresh.get_tooltip_text() == "Refresh (F5)"


def test_the_filter_bar_reads_in_english(window_factory: WindowFactory, snapshot: Snapshot) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    texts = _texts(window.overview)
    search = next(w for w in descendants(window.overview) if isinstance(w, Gtk.SearchEntry))

    assert search.get_placeholder_text() == "Search…"
    assert any(t.startswith("To free up (") for t in texts)
    assert any(t.startswith("All (") for t in texts)
    assert "More filters" in texts
    # The popover content: both headings and a category and a risk choice.
    assert {"Program type", "Risk", "Browser", "Safe"} <= set(texts)
    assert "Da liberare" not in " ".join(texts)


def test_the_loading_state_and_the_error_state_are_english(display: None) -> None:
    loading = LoadingView()
    loading.mark_slow()
    error = ErrorView()
    error.show_cause(failures=3)

    assert loading.page.get_title() == "Collecting data…"
    assert loading.page.get_description() == "This is taking longer than expected"
    assert error.page.get_title() == "I cannot read the computer's data"
    assert error.restart.get_label() == "Try again now"
    assert (error.page.get_description() or "").startswith("I tried 3 times in a row")


def test_the_failure_cause_has_a_singular_form(display: None) -> None:
    assert failure_cause(failures=1).startswith("I tried 1 time in a row")


def test_an_expanded_group_row_reads_in_english(window_factory: WindowFactory) -> None:
    window = window_factory(FakeActionService(snapshot=one_group()))
    open_group(window)

    texts = _texts(window.overview)

    assert any(t.startswith("Can be freed: ") and " · in use: " in t for t in texts)
    assert {
        "Don't alert me about this",
        "1 hour",
        "1 day",
        "7 days",
        "Never again",
        "Technical details",
    } <= set(texts)
    assert "Mai più" not in texts


def test_the_ignored_group_offers_to_turn_alerts_back_on(window_factory: WindowFactory) -> None:
    window = window_factory(FakeActionService(snapshot=one_group(ignored=True)))
    open_group(window)

    texts = _texts(window.overview)

    assert "Turn alerts back on" in texts
    assert "Never again" not in texts
    assert "You get no alerts for this program" in texts


def test_the_disk_page_header_reads_in_english(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeDiskSource(snapshot=snapshot))
    present_and_settle(window)

    texts = _texts(window.disk)

    assert {"Check now", "No check yet"} <= set(texts)
    assert "The first check starts shortly after launch. You can start it with Check now." in texts
    assert "Every button first shows you what will happen and asks for confirmation." in texts
    assert "Only cleans what recreates itself: the trash and your data stay." in texts


def test_the_muted_banner_names_the_end_of_the_mute_in_english() -> None:
    source = FakeActionService(snapshot=_empty_snapshot())
    source.notifications_muted_until = datetime.fromisoformat("2026-10-16T14:30:00+02:00")

    menu, entry = build_main_menu(source=source)

    assert _menu_labels(menu) == [
        "Preferences",
        "Notifications muted until 14:30",
        "About",
        "Quit",
    ]
    assert not entry.action.get_enabled()


def test_the_mute_entry_goes_back_to_its_plain_label_when_the_mute_ends() -> None:
    source = FakeActionService(snapshot=_empty_snapshot())
    source.notifications_muted_until = datetime.fromisoformat("2026-10-16T14:30:00+02:00")
    menu, entry = build_main_menu(source=source)

    source.notifications_muted_until = None
    entry.sync()

    assert _menu_labels(menu)[1] == "Mute for 1 h"
    assert entry.action.get_enabled()


def _empty_snapshot() -> Snapshot:
    return one_group()
