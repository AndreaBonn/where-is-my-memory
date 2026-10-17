from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import gi

from wimm.core.constants import DEVDIRS_MIN_AGE_DAYS
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.ui.disk_model import DiskRowView
from wimm.ui.pages.disk import DiskPage
from wimm.ui.window_state import SnapshotSource

gi.require_version("GObject", "2.0")
from gi.repository import GObject

REPORT_SIGNAL = "disk-report-updated"
FAILED_SIGNAL = "disk-scan-failed"
STARTED_SIGNAL = "disk-scan-started"


class DiskBinding:
    """Connects the Disco page to a source that has the disk scan; inert on one that has not."""

    def __init__(
        self,
        *,
        source: SnapshotSource,
        clock: Callable[[], datetime],
        start: Callable[[ActionRequest, str | None], None] | None = None,
    ) -> None:
        self._source, self._clock, self._start = source, clock, start
        self._handlers: list[int] = []
        acting = start is not None
        self.page = DiskPage(
            on_rescan=self._rescan,
            on_action=self._row_action if acting else None,
            on_section=self._section_action if acting else None,
        )
        if self._has_disk_scan():
            self._handlers = [
                source.connect(REPORT_SIGNAL, self._on_report),
                source.connect(FAILED_SIGNAL, self._on_failed),
                source.connect(STARTED_SIGNAL, self._on_started),
            ]
            self._on_report()
            if getattr(self._source, "disk_scanning", lambda: False)():
                self.page.begin_scan()

    def _has_disk_scan(self) -> bool:
        source = cast(GObject.Object, self._source)
        names = (REPORT_SIGNAL, FAILED_SIGNAL, STARTED_SIGNAL)
        return all(GObject.signal_lookup(name, source) for name in names)

    def _rescan(self) -> None:
        rescan = getattr(self._source, "rescan_disk", None)
        if callable(rescan):
            rescan()

    def _row_action(self, row: DiskRowView) -> None:
        """Plan the row's action; the request is the one the planner reads from the report."""
        if self._start is None or row.action_kind is None:
            return
        target = None if row.target_id is None else TargetId(row.target_id)
        self._start(ActionRequest(kind=row.action_kind, target_id=target), row.title)

    def _section_action(self, kind: ActionKind) -> None:
        if self._start is not None:
            self._start(ActionRequest(kind=kind), None)

    def _min_age_days(self) -> int:
        config: Any = getattr(self._source, "config", None)
        return config().devdirs_min_age_days if callable(config) else DEVDIRS_MIN_AGE_DAYS

    def _on_report(self, *_args: object) -> None:
        report = getattr(self._source, "disk_report", lambda: None)()
        self.page.show_report(report=report, now=self._clock(), min_age_days=self._min_age_days())

    def _on_started(self, *_args: object) -> None:
        self.page.begin_scan()

    def _on_failed(self, *_args: object) -> None:
        self.page.show_scan_failed()

    def close(self) -> None:
        """Drop the signal handlers; the source outlives the window."""
        for handler in self._handlers:
            self._source.disconnect(handler)
        self._handlers = []
