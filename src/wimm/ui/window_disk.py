from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import gi

from wimm.core.constants import DEVDIRS_MIN_AGE_DAYS
from wimm.ui.pages.disk import DiskPage
from wimm.ui.window_state import SnapshotSource

gi.require_version("GObject", "2.0")
from gi.repository import GObject

REPORT_SIGNAL = "disk-report-updated"
FAILED_SIGNAL = "disk-scan-failed"
STARTED_SIGNAL = "disk-scan-started"


class DiskBinding:
    """Connects the Disco page to a source that has the disk scan; inert on one that has not."""

    def __init__(self, *, source: SnapshotSource, clock: Callable[[], datetime]) -> None:
        self._source, self._clock = source, clock
        self._handlers: list[int] = []
        self.page = DiskPage(on_rescan=self._rescan)
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
