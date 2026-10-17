import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from wimm import __version__
from wimm.model.actions import ActionRequest
from wimm.paths import default_user_paths
from wimm.ui.action_flow import can_act
from wimm.ui.dialogs.tray_help import TRAY_MISSING_TEXT as TRAY_MISSING_TEXT
from wimm.ui.dialogs.tray_help import tray_banner
from wimm.ui.dialogs.welcome import welcome_if_first_run
from wimm.ui.pages.overview import OverviewPage
from wimm.ui.widgets import install_style, name_icon_button
from wimm.ui.window_actions import build_action_flow
from wimm.ui.window_disk import DiskBinding
from wimm.ui.window_notify import build_main_menu, group_controls
from wimm.ui.window_shortcuts import shortcut_controller
from wimm.ui.window_state import (
    MIN_HEIGHT,
    MIN_WIDTH,
    STATE_FILE,
    SnapshotSource,
    load_window_size,
    save_window_size,
)

LOGGER = logging.getLogger(__name__)
APPLICATION_ID = "io.github.wimm.WhereIsMyMemory"
WINDOW_TITLE = "Where Is My Memory"
NARROW_CONDITION = "max-width: 600px"
FAILURE_LIMIT = 3
FAILURE_POLL_SECONDS = 2
SAVE_DELAY_MS = 500
ACTION_REFRESH = "win.refresh"
ABOUT_COMMENTS = "Mostra dove va la memoria e cosa si può liberare."


class MainWindow(Adw.Window):
    """The resident panel: hidden on close, built on first use, updated while visible."""

    def __init__(
        self,
        *,
        application: Gio.Application,
        source: SnapshotSource,
        clock: Callable[[], datetime],
        state_dir: Path,
    ) -> None:
        super().__init__(title=WINDOW_TITLE)
        install_style()
        self._source, self._clock = source, clock
        self._state_dir, self._state_path = state_dir, state_dir / STATE_FILE
        self._dirty = False
        self._last_failures = -1
        self._save_timer = self._poll_timer = 0
        self._source_handler = 0
        self._init_actions(application=application)
        width, height = load_window_size(path=self._state_path)
        self.set_default_size(width, height)
        self.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        self._build_pages()
        self._build_chrome()
        self._init_actions_flow()
        self._build_shortcuts()
        self._connect_signals()
        self.sync()

    def _build_pages(self) -> None:
        self.overview = OverviewPage(
            on_action=self._start_action if can_act(source=self._source) else None,
            controls=group_controls(source=self._source),
        )
        self.system = self.overview.system
        start = self._start_action if can_act(source=self._source) else None
        self._disk = DiskBinding(source=self._source, clock=self._clock, start=start)
        self.disk = self._disk.page

    def _init_actions(self, *, application: Gio.Application) -> None:
        self.insert_action_group("app", application)
        self._actions = Gio.SimpleActionGroup()
        self.insert_action_group("win", self._actions)

    @property
    def window_actions(self) -> Gio.SimpleActionGroup:
        """The ``win`` action group (the preferences action is added by the application shell)."""
        return self._actions

    def _connect_signals(self) -> None:
        self.connect("close-request", self._on_close_request)
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.connect("notify::default-width", self._schedule_save)
        self.connect("notify::default-height", self._schedule_save)
        self._source_handler = self._source.connect("snapshot-updated", self._on_snapshot_updated)

    def _init_actions_flow(self) -> None:
        self.action_flow = build_action_flow(
            parent=self, source=self._source, toasts=self.toasts, on_busy=self._set_busy
        )

    def _set_busy(self, busy: bool) -> None:
        self.overview.set_busy(busy=busy)
        self.disk.set_busy(busy=busy)

    def _start_action(self, request: ActionRequest, subject: str | None) -> None:
        if self.action_flow is not None:
            self.action_flow.start(request=request, subject=subject)

    @property
    def can_refresh(self) -> bool:
        """True when the source can be asked for a new sample."""
        return callable(getattr(self._source, "request_refresh", None))

    def _build_chrome(self) -> None:
        stack = Adw.ViewStack()
        stack.add_titled_with_icon(self.overview, "overview", "Panoramica", "view-list-symbolic")
        stack.add_titled_with_icon(self.disk, "disk", "Disco", "drive-harddisk-symbolic")
        self.view_stack = stack
        switcher = Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        bar = Adw.ViewSwitcherBar(stack=stack)
        header = Adw.HeaderBar(title_widget=switcher)
        header.pack_end(self._menu_button())
        header.pack_end(self._refresh_button())
        toolbar = Adw.ToolbarView(content=stack)
        toolbar.add_top_bar(header)
        self.tray_banner = tray_banner(parent=self)
        toolbar.add_top_bar(self.tray_banner)
        toolbar.add_bottom_bar(bar)
        self.toasts = Adw.ToastOverlay(child=toolbar)
        self.set_content(self.toasts)
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(NARROW_CONDITION))
        breakpoint_.add_setter(bar, "reveal", True)
        breakpoint_.add_setter(switcher, "visible", False)
        breakpoint_.connect("apply", lambda *_a: self.overview.set_narrow(narrow=True))
        breakpoint_.connect("unapply", lambda *_a: self.overview.set_narrow(narrow=False))
        self.add_breakpoint(breakpoint_)

    def _menu_button(self) -> Gtk.MenuButton:
        menu, self._snooze_all = build_main_menu(source=self._source)
        self._actions.add_action(self._snooze_all.action)
        button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True)
        name_icon_button(button=button, label="Menu principale")
        self._add_window_action(name="about", handler=self._show_about)
        return button

    def _refresh_button(self) -> Gtk.Button:
        self._add_window_action(name="refresh", handler=lambda *_a: self.refresh())
        button = Gtk.Button(icon_name="view-refresh-symbolic", action_name=ACTION_REFRESH)
        name_icon_button(button=button, label="Aggiorna (F5)")
        button.set_visible(self.can_refresh)
        return button

    def _add_window_action(self, *, name: str, handler: Callable[..., None]) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", handler)
        self._actions.add_action(action)

    def _build_shortcuts(self) -> None:
        self.add_controller(
            shortcut_controller(on_refresh=self.refresh, on_find=self.overview.focus_search)
        )

    def _show_about(self, *_args: object) -> None:
        Adw.AboutDialog(
            application_name=WINDOW_TITLE,
            application_icon=APPLICATION_ID,
            version=__version__,
            comments=ABOUT_COMMENTS,
            license_type=Gtk.License.GPL_3_0,
        ).present(self)

    def refresh(self) -> None:
        """Ask the source for a new sample, if it can."""
        request = getattr(self._source, "request_refresh", None)
        if callable(request):
            request()

    def sync(self) -> None:
        """Rebuild what the pages show from the source's current state."""
        self._dirty = False
        failures = self._source.consecutive_failures
        self._last_failures = failures
        self._snooze_all.sync()
        snapshot = self._source.snapshot()
        if failures >= FAILURE_LIMIT:
            self.overview.show_error(failures=failures)
        elif snapshot is None:
            self.overview.show_loading()
        else:
            self.overview.show_snapshot(snapshot=snapshot, now=self._clock())
        if snapshot is None:
            self.system.show_waiting()
        else:
            self.system.show_snapshot(snapshot=snapshot)

    def set_tray_missing(self, missing: bool) -> None:
        """Show the banner that explains the absent tray icon, or hide it."""
        self.tray_banner.set_revealed(missing)

    def show_group(self, group_id: str | None) -> None:
        """Present the window in front; with an id, expand that group in the Panoramica."""
        self.present()
        if self._dirty:
            self.sync()
        if group_id is not None:
            self.view_stack.set_visible_child_name("overview")
            self.overview.expand_group(group_id=group_id)
        welcome_if_first_run(parent=self, state_dir=self._state_dir)

    def _on_snapshot_updated(self, *_args: object) -> None:
        # A hidden window is rebuilt when it is shown again, not on every sample.
        if self.get_mapped():
            self.sync()
        else:
            self._dirty = True

    def _on_map(self, *_args: object) -> None:
        if self._dirty:
            self.sync()
        if not self._poll_timer:
            self._poll_timer = GLib.timeout_add_seconds(FAILURE_POLL_SECONDS, self._poll_failures)
        # Failures that piled up while hidden show at once, not after the first poll.
        self._poll_failures()

    def _on_unmap(self, *_args: object) -> None:
        self._stop_timers()

    def destroy(self) -> None:
        """Destroy the window; the source outlives it, so drop the handler and the timers."""
        # GTK 4 widgets have no "destroy" signal and do_dispose is not called by destroy().
        if self._source_handler:
            self._source.disconnect(self._source_handler)
            self._source_handler = 0
        self._stop_timers()
        self._disk.close()
        if self.action_flow is not None:
            self.action_flow.close()
        self.overview.cancel()
        if self._save_timer:
            GLib.source_remove(self._save_timer)
            self._save_timer = 0
        super().destroy()

    def _stop_timers(self) -> None:
        if self._poll_timer:
            GLib.source_remove(self._poll_timer)
            self._poll_timer = 0

    def _poll_failures(self) -> bool:
        # Failed cycles emit no signal, so the failure count is watched while visible.
        if self._source.consecutive_failures != self._last_failures:
            self.sync()
        return GLib.SOURCE_CONTINUE

    def _on_close_request(self, *_args: object) -> bool:
        self.save_size()
        self.set_visible(False)
        return True

    def _schedule_save(self, *_args: object) -> None:
        if not self._save_timer:
            self._save_timer = GLib.timeout_add(SAVE_DELAY_MS, self._save_later)

    def _save_later(self) -> bool:
        self._save_timer = 0
        self.save_size()
        return GLib.SOURCE_REMOVE

    def save_size(self) -> None:
        """Write the current size to window.json (width and height only)."""
        # The default size is what set_default_size takes back on the next start; the
        # allocation excludes the client-side shadow, so saving it would shrink the window
        # a little at every restart.
        width, height = self.get_default_size()
        if width <= 0 or height <= 0:
            width, height = self.get_width(), self.get_height()
        save_window_size(path=self._state_path, width=width, height=height)


def create_main_window(
    *,
    application: Gio.Application,
    source: SnapshotSource,
    clock: Callable[[], datetime],
    state_dir: Path | None = None,
) -> MainWindow:
    """Build the panel window; GTK and libadwaita are imported on the first call.

    ``state_dir`` defaults to the user state directory; tests pass a temporary one.
    """
    Adw.init()
    directory = state_dir if state_dir is not None else default_user_paths().state_dir
    return MainWindow(application=application, source=source, clock=clock, state_dir=directory)
