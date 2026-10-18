"""Branches of the UI widgets and pages that no other test reaches."""

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from tests.ui.conftest import (
    all_filter,
    descendants,
    main_context_iterate,
    make_group,
    with_groups,
)
from wimm.model.enums import ActivityState
from wimm.model.snapshot import Snapshot
from wimm.ui import widgets as widgets_module
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.viewmodel import build_rows
from wimm.ui.views import MemberRow, RowFilters
from wimm.ui.widgets import contrast_installed, install_style, sync_contrast
from wimm.ui.widgets.context_menu import MenuTarget, install_context_actions
from wimm.ui.widgets.group_controls import (
    IGNORE_BUTTON_NAME,
    SNOOZE_BUTTON_PREFIX,
    GroupControlHandlers,
    GroupControls,
)
from wimm.ui.widgets.group_row import PRIMARY_ACTION_NAME, GroupRowWidget
from wimm.ui.widgets.member_row import member_subtitle
from wimm.ui.widgets.scroll_restore import ScrollRestore
from wimm.ui.widgets.system_section import SystemSection

pytestmark = pytest.mark.ui
OUR_BUTTONS = (PRIMARY_ACTION_NAME, IGNORE_BUTTON_NAME)


def buttons_of(widget: Gtk.Widget) -> list[Gtk.Button]:
    return [w for w in descendants(widget) if isinstance(w, Gtk.Button)]


# --- OverviewPage -----------------------------------------------------------------------


@pytest.fixture
def overview(display: None) -> OverviewPage:
    install_style()
    return OverviewPage()


def test_expanding_an_unknown_group_reports_failure_and_a_known_one_succeeds(
    overview: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    shown = with_groups(snapshot, make_group("alpha"), make_group("beta"))
    overview.show_snapshot(snapshot=shown, now=now)

    assert overview.expand_group(group_id="id-missing") is False
    assert overview.expand_group(group_id="id-alpha") is True
    assert overview.group_widgets["id-alpha"].get_expanded()
    assert not overview.group_widgets["id-beta"].get_expanded()


def test_a_filter_change_before_the_first_snapshot_builds_nothing_and_is_honoured_later(
    overview: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    all_filter(overview).set_active(True)
    main_context_iterate()
    assert overview.group_widgets == {}
    assert overview.visible_state == "loading"

    busy = make_group("busy", state=ActivityState.ACTIVE)
    overview.show_snapshot(snapshot=with_groups(snapshot, make_group("idle"), busy), now=now)
    main_context_iterate()

    assert set(overview.group_widgets) == {"id-idle", "id-busy"}


def test_without_an_action_handler_the_row_and_summary_buttons_are_inert(
    overview: OverviewPage, snapshot: Snapshot, now: datetime
) -> None:
    overview.show_snapshot(snapshot=with_groups(snapshot, make_group("alpha")), now=now)
    main_context_iterate()
    primary = [b for b in buttons_of(overview) if b.get_name() == PRIMARY_ACTION_NAME]
    assert len(primary) == 1
    assert not primary[0].get_sensitive()
    assert primary[0].get_tooltip_text()

    plain = [b for b in buttons_of(overview) if type(b) is Gtk.Button]
    assert len(plain) >= 1
    for button in plain:
        button.emit("clicked")  # nothing is connected: must not raise

    assert overview.visible_state == "content"


# --- Disco page -------------------------------------------------------------------------


def test_system_section_drops_the_old_rows_when_the_protected_summary_changes(
    display: None, snapshot: Snapshot
) -> None:
    section = SystemSection()
    section.show_snapshot(snapshot=snapshot)
    header = section.expander.get_title()

    def titles() -> list[str]:
        return [
            w.get_title()
            for w in descendants(section.expander)
            if isinstance(w, Adw.ActionRow) and w.get_title() != header
        ]

    assert "Sessione GNOME" in titles()
    renamed = tuple(replace(item, label="Servizio nuovo") for item in snapshot.protected_summary)
    section.show_snapshot(snapshot=replace(snapshot, protected_summary=renamed))

    assert "Sessione GNOME" not in titles()
    assert "Servizio nuovo" in titles()


def test_member_subtitle_names_the_image_with_or_without_its_state() -> None:
    base = MemberRow(
        key="abc123", kind="container", name="db", title="db", command=None, cwd=None, ports="",
        started=None, memory="10 MB", image="postgres:16", state=None, mounts=(),
        activity="inattivo", actions=(),
    )  # fmt: skip
    assert "immagine postgres:16" in member_subtitle(member=base).split("\n")
    running = replace(base, state="exited")
    assert "immagine postgres:16 (exited)" in member_subtitle(member=running).split("\n")


def test_sync_contrast_without_a_display_changes_nothing(
    display: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_style()
    before = set(widgets_module._contrast_on)
    with monkeypatch.context() as patch:
        patch.setattr(Gdk.Display, "get_default", staticmethod(lambda: None))
        sync_contrast(high_contrast=True)
        sync_contrast(high_contrast=False)
    assert widgets_module._contrast_on == before
    # Positive control: with the display back, the same call does switch it.
    was_on = contrast_installed()
    try:
        sync_contrast(high_contrast=was_on)
        assert contrast_installed() is not was_on
    finally:
        sync_contrast(high_contrast=not was_on)


def test_scroll_restore_puts_the_position_back_unless_the_user_moved_meanwhile(
    display: None,
) -> None:
    scroller = Gtk.ScrolledWindow()
    scroller.set_vadjustment(Gtk.Adjustment(value=0, lower=0, upper=1000, step_increment=1,
                                            page_increment=10, page_size=100))  # fmt: skip
    adjustment = scroller.get_vadjustment()
    restore = ScrollRestore(scroller=scroller)

    restore.queue(position=300)
    main_context_iterate()
    assert adjustment.get_value() == 300

    restore.queue(position=500)
    adjustment.set_value(50)  # the user scrolled before the idle ran
    main_context_iterate()
    assert adjustment.get_value() == 50


def open_folder_action(*, path: str) -> Gio.SimpleActionGroup:
    owner = Gtk.Box()
    return install_context_actions(owner=owner, target=MenuTarget(command=None, pid=None, cwd=path))


def test_open_folder_asks_the_desktop_for_the_folder_uri(
    display: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        Gio.AppInfo, "launch_default_for_uri", staticmethod(lambda uri, ctx: opened.append(uri))
    )
    open_folder_action(path=str(tmp_path)).activate_action("open-folder", None)
    assert opened == [f"file://{tmp_path}"]


def test_open_folder_failure_is_logged_with_the_path_and_does_not_raise(
    display: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(uri: str, ctx: object) -> None:
        raise GLib.Error("no handler")

    monkeypatch.setattr(Gio.AppInfo, "launch_default_for_uri", staticmethod(refuse))
    with caplog.at_level(logging.WARNING):
        open_folder_action(path=str(tmp_path)).activate_action("open-folder", None)
    assert f"Could not open folder {tmp_path}" in caplog.messages


def test_group_controls_without_handlers_are_disabled_and_clicks_raise_nothing(
    display: None,
) -> None:
    calls: list[str] = []
    wired = GroupControlHandlers(
        on_snooze=lambda group, _hours: calls.append(f"snooze {group}"),
        on_ignore=lambda group, _ignored: calls.append(f"ignore {group}"),
    )
    with_handlers = buttons_of(GroupControls(group_id="g", ignored=False, handlers=wired))
    without = buttons_of(GroupControls(group_id="g", ignored=False, handlers=None))

    assert any(b.get_name() == IGNORE_BUTTON_NAME for b in without)
    assert not any(b.get_sensitive() for b in without)
    for button in without:
        button.emit("clicked")
    assert calls == []
    # Paired positive: the same ignore button with handlers does reach them.
    next(b for b in with_handlers if b.get_name() == IGNORE_BUTTON_NAME).emit("clicked")
    assert calls == ["ignore g"]


def test_group_row_without_handlers_expands_and_its_controls_are_inert(
    display: None, snapshot: Snapshot, now: datetime
) -> None:
    install_style()
    (row, *_rest) = build_rows(snapshot=snapshot, filters=RowFilters(), now=now)
    widget = GroupRowWidget(row=row)
    widget.set_expanded(True)
    main_context_iterate()

    # Only our own buttons: the expander's internal toggle is not ours to click.
    ours = [
        b
        for b in buttons_of(widget)
        if b.get_name() in OUR_BUTTONS or b.get_name().startswith(SNOOZE_BUTTON_PREFIX)
    ]
    assert {b.get_name() for b in ours} >= {PRIMARY_ACTION_NAME, IGNORE_BUTTON_NAME}
    for button in ours:
        button.emit("clicked")

    primary = [b for b in ours if b.get_name() == PRIMARY_ACTION_NAME]
    assert all(not b.get_sensitive() for b in primary)
    assert widget.get_expanded()
