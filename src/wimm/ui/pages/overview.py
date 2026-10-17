import logging
import time
from collections.abc import Callable, Generator
from datetime import datetime

from gi.repository import Adw, GLib, Gtk

from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind
from wimm.model.snapshot import Snapshot
from wimm.ui.requests import request_for_row
from wimm.ui.viewmodel import build_rows, build_summary, empty_state
from wimm.ui.views import GroupRow, RowFilters
from wimm.ui.widgets.group_list import build_list
from wimm.ui.widgets.group_row import GroupRowWidget
from wimm.ui.widgets.state_views import EmptyView, ErrorView, LoadingView
from wimm.ui.widgets.summary import FilterBar, SummaryPanel

LOGGER = logging.getLogger(__name__)
SLOW_LOADING_MS = 15_000
MAX_CONTENT_WIDTH = 1000
PAGE_MARGIN = 12
SECTION_SPACING = 12
STATE_LOADING = "loading"
STATE_ERROR = "error"
STATE_CONTENT = "content"
LIST_PAGE = "list"
EMPTY_PAGE = "empty"
# RNF-03: the main loop is never blocked for more than 50 ms; a slice stops after 10 ms
# of row work and the rest of the update waits for the next idle iteration.
SLICE_BUDGET_S = 0.010


class OverviewPage(Gtk.Stack):
    """Panoramica: summary, filters and one expandable row per actionable group."""

    def __init__(
        self,
        *,
        slow_loading_ms: int = SLOW_LOADING_MS,
        on_action: Callable[[ActionRequest, str | None], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_action = on_action
        self._slow_ms = slow_loading_ms
        self._slow_timer = 0
        self._loading_started = False
        self._snapshot: Snapshot | None = None
        self._now: datetime | None = None
        self._narrow = False
        self._widgets: dict[str, GroupRowWidget] = {}
        self._job: Generator[None] | None = None
        self._job_source = 0
        self._sort_dirty = False
        self._scroll_position = 0.0
        self._restore_source = 0
        self._loading = LoadingView()
        self._error = ErrorView()
        self._empty = EmptyView()
        self._summary = SummaryPanel(on_stop_all=None if on_action is None else self._on_stop_all)
        self._filters = FilterBar(on_changed=self._on_filters_changed)
        self._list = build_list()
        self._build_pages()
        self.show_loading()

    def _build_pages(self) -> None:
        self._list_stack = Gtk.Stack()
        self._list_stack.add_named(self._list, LIST_PAGE)
        self._list_stack.add_named(self._empty.page, EMPTY_PAGE)
        self._scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._scroller.set_child(self._build_content())
        self.add_named(self._loading.page, STATE_LOADING)
        self.add_named(self._error.page, STATE_ERROR)
        self.add_named(self._scroller, STATE_CONTENT)

    def _build_content(self) -> Adw.Clamp:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=SECTION_SPACING,
            margin_top=PAGE_MARGIN,
            margin_bottom=PAGE_MARGIN,
            margin_start=PAGE_MARGIN,
            margin_end=PAGE_MARGIN,
        )
        for child in (self._summary, self._filters, self._list_stack):
            box.append(child)
        return Adw.Clamp(maximum_size=MAX_CONTENT_WIDTH, child=box)

    @property
    def visible_state(self) -> str:
        """Name of the state currently shown: loading, error or content."""
        return self.get_visible_child_name() or STATE_LOADING

    @property
    def is_syncing(self) -> bool:
        """True while rows are still being built or updated in idle slices."""
        return self._job is not None

    @property
    def group_widgets(self) -> dict[str, GroupRowWidget]:
        """Rows currently built, by group id."""
        return self._widgets

    def focus_search(self) -> None:
        """Move the focus to the search entry (Ctrl+F)."""
        self._filters.search.grab_focus()

    def show_loading(self) -> None:
        """Show the spinner and arm the 15 s fallback text; repeated calls keep the timer."""
        if self._loading_started:
            return
        self._loading_started = True
        self._loading.reset()
        self.set_visible_child_name(STATE_LOADING)
        self._slow_timer = GLib.timeout_add(self._slow_ms, self._on_slow)

    def show_error(self, *, failures: int) -> None:
        """Show the monitor-not-responding page."""
        self._cancel_slow()
        self._error.show_cause(failures=failures)
        self.set_visible_child_name(STATE_ERROR)

    def show_snapshot(self, *, snapshot: Snapshot, now: datetime) -> None:
        """Show data; rows are updated in place, keeping expansion, filters and scroll."""
        self._cancel_slow()
        self._snapshot, self._now = snapshot, now
        self._render()
        self.set_visible_child_name(STATE_CONTENT)

    def set_narrow(self, *, narrow: bool) -> None:
        """Apply the one-column layout to every row."""
        self._narrow = narrow
        for widget in self._widgets.values():
            widget.set_narrow(narrow=narrow)

    def expand_group(self, *, group_id: str) -> bool:
        """Expand and focus a group, clearing the filters if they hide it."""
        self._flush_rows()
        if group_id not in self._widgets:
            self._filters.reset()
            self._flush_rows()
        widget = self._widgets.get(group_id)
        if widget is None:
            return False
        widget.set_expanded(True)
        widget.grab_focus()
        return True

    def _on_row_action(self, row: GroupRow) -> None:
        request = request_for_row(row=row)
        if request is not None and self._on_action is not None:
            self._on_action(request, row.title)

    def _on_stop_all(self) -> None:
        if self._on_action is not None:
            self._on_action(ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE), None)

    def _on_slow(self) -> bool:
        self._slow_timer = 0
        self._loading.mark_slow()
        return GLib.SOURCE_REMOVE

    def _cancel_slow(self) -> None:
        self._loading_started = False
        if self._slow_timer:
            GLib.source_remove(self._slow_timer)
            self._slow_timer = 0

    def _on_filters_changed(self, _filters: RowFilters) -> None:
        if self._snapshot is not None:
            self._render()

    def _render(self) -> None:
        if self._snapshot is None or self._now is None:
            return
        filters = self._filters.filters
        rows = build_rows(snapshot=self._snapshot, filters=filters, now=self._now)
        self._summary.update(view=build_summary(snapshot=self._snapshot))
        self._start_sync(rows=rows, scroll_position=self._scroller.get_vadjustment().get_value())
        state = empty_state(snapshot=self._snapshot, filters=filters)
        if state is None:
            self._list_stack.set_visible_child_name(LIST_PAGE)
        else:
            self._empty.show_state(state=state)
            self._list_stack.set_visible_child_name(EMPTY_PAGE)

    def cancel(self) -> None:
        """Drop the running sync, the pending scroll restore and the loading timer."""
        self._cancel_rows()
        self._cancel_restore()
        self._cancel_slow()

    def _restore_scroll(self, position: float, expected: float) -> bool:
        self._restore_source = 0
        adjustment = self._scroller.get_vadjustment()
        # A moved value means something else (the user, a focus change) scrolled meanwhile.
        if adjustment.get_value() == expected:
            adjustment.set_value(position)
        return GLib.SOURCE_REMOVE

    def _cancel_restore(self) -> None:
        if self._restore_source:
            GLib.source_remove(self._restore_source)
            self._restore_source = 0

    def _start_sync(self, *, rows: tuple[GroupRow, ...], scroll_position: float) -> None:
        """Replace any running sync with one for ``rows``; the first slice runs now."""
        self._cancel_rows()
        self._cancel_restore()
        self._job = self._sync_steps(rows=rows)
        self._scroll_position = scroll_position
        if not self._advance(budget_s=SLICE_BUDGET_S, restore=True):
            self._job_source = GLib.idle_add(self._on_sync_idle)

    def _on_sync_idle(self) -> bool:
        self._job_source = 0
        if not self._advance(budget_s=SLICE_BUDGET_S, restore=True):
            self._job_source = GLib.idle_add(self._on_sync_idle)
        return GLib.SOURCE_REMOVE

    def _advance(self, *, budget_s: float | None, restore: bool) -> bool:
        """Run the pending sync until it ends or the budget is spent; True when finished.

        ``restore`` queues the scroll restore at the end; a flush must not, because its
        callers move the scroll themselves (focus on a row) right after.
        """
        job = self._job
        if job is None:
            return True
        deadline = None if budget_s is None else time.monotonic() + budget_s
        try:
            for _ in job:
                if deadline is not None and time.monotonic() >= deadline:
                    return False
        except Exception:
            self._job = None
            LOGGER.exception("Panoramica row sync failed")
            return True
        self._job = None
        if restore:
            self._queue_restore()
        return True

    def _queue_restore(self) -> None:
        self._cancel_restore()
        expected = self._scroller.get_vadjustment().get_value()
        self._restore_source = GLib.idle_add(self._restore_scroll, self._scroll_position, expected)

    def _cancel_rows(self) -> None:
        if self._job_source:
            GLib.source_remove(self._job_source)
            self._job_source = 0
        if self._job is not None:
            self._job.close()
            self._job = None

    def _flush_rows(self) -> None:
        """Finish a pending sync at once, for callers that need every row to exist."""
        if self._job_source:
            GLib.source_remove(self._job_source)
            self._job_source = 0
        self._advance(budget_s=None, restore=False)

    def _sync_steps(self, *, rows: tuple[GroupRow, ...]) -> Generator[None]:
        """Yield after each row touched, so the driver can stop at the slice budget."""
        wanted = {row.id for row in rows}
        for group_id in [gid for gid in self._widgets if gid not in wanted]:
            self._list.remove(self._widgets.pop(group_id))
            yield
        for rank, row in enumerate(rows):
            widget = self._widgets.get(row.id)
            if widget is None:
                widget = GroupRowWidget(
                    row=row, on_action=None if self._on_action is None else self._on_row_action
                )
                widget.set_narrow(narrow=self._narrow)
                widget.sort_rank = rank
                self._widgets[row.id] = widget
                self._list.append(widget)
                self._sort_dirty = True
            else:
                widget.update(row=row)
                self._sort_dirty = self._sort_dirty or widget.sort_rank != rank
                widget.sort_rank = rank
            yield
        if self._sort_dirty:
            self._sort_dirty = False
            self._list.invalidate_sort()
