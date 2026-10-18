from collections.abc import Callable

from gi.repository import Adw, Gtk

from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind
from wimm.model.snapshot import Snapshot
from wimm.ui.disk_texts import DiskTotals
from wimm.ui.viewmodel import build_summary
from wimm.ui.widgets.summary import SummaryPanel

# The name the window gives the Disco page in its view stack.
DISK_PAGE = "disk"

type StartAction = Callable[[ActionRequest, str | None], None]


def _request(*, start: StartAction | None, kind: ActionKind) -> Callable[[], None] | None:
    return None if start is None else lambda: start(ActionRequest(kind=kind), None)


class OverviewSummary:
    """The Panoramica's summary panel and what it needs beyond the snapshot.

    The disk totals come from the Disco page, so both pages promise the same amount;
    they stay None until the first disk scan.
    """

    def __init__(self, *, page: Gtk.Widget, start: StartAction | None) -> None:
        self._page = page
        self.disk_totals: DiskTotals | None = None
        self.panel = SummaryPanel(
            on_stop_all=_request(start=start, kind=ActionKind.STOP_ALL_IDLE_SAFE),
            on_free_disk=_request(start=start, kind=ActionKind.DISK_FREE_SAFE),
            on_show_disk=self._show_disk,
        )

    def update(self, *, snapshot: Snapshot) -> None:
        """Redraw the panel from a snapshot and the latest disk totals."""
        self.panel.update(view=build_summary(snapshot=snapshot, disk_totals=self.disk_totals))

    def _show_disk(self) -> None:
        stack = self._page.get_ancestor(Adw.ViewStack)
        if isinstance(stack, Adw.ViewStack):
            stack.set_visible_child_name(DISK_PAGE)
