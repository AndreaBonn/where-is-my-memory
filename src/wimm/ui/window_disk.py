from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import gi

from wimm.core.constants import DEVDIRS_MIN_AGE_DAYS
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.ui.disk_model import DiskRowView, RootsState
from wimm.ui.format import home_relative
from wimm.ui.pages.disk import DiskPage
from wimm.ui.window_shortcuts import ACTION_FOLDERS
from wimm.ui.window_state import SnapshotSource

gi.require_version("GObject", "2.0")
from gi.repository import GObject

REPORT_SIGNAL = "disk-report-updated"
FAILED_SIGNAL = "disk-scan-failed"
STARTED_SIGNAL = "disk-scan-started"
SNAPSHOT_SIGNAL = "snapshot-updated"


class DiskBinding:
    """Connects the Disco page to a source that has the disk scan; inert on one that has not."""

    def __init__(
        self,
        *,
        source: SnapshotSource,
        clock: Callable[[], datetime],
        start: Callable[[ActionRequest, str | None], None] | None = None,
        on_choose_folder: Callable[[], None] | None = None,
    ) -> None:
        self._source, self._clock, self._start = source, clock, start
        self._handlers: list[int] = []
        self._roots = RootsState()
        self._seen_roots: tuple[Path, ...] | None = None
        acting = start is not None
        self.page = DiskPage(
            on_rescan=self._rescan,
            on_action=self._row_action if acting else None,
            on_section=self._section_action if acting else None,
            on_choose_folder=on_choose_folder or self._open_folders,
        )
        if self._has_disk_scan():
            self._handlers = [
                source.connect(REPORT_SIGNAL, self._on_report),
                source.connect(FAILED_SIGNAL, self._on_failed),
                source.connect(STARTED_SIGNAL, self._on_started),
                source.connect(SNAPSHOT_SIGNAL, self._on_snapshot),
            ]
            self._on_report()
            if getattr(self._source, "disk_scanning", lambda: False)():
                self.page.begin_scan()

    def _has_disk_scan(self) -> bool:
        source = cast(GObject.Object, self._source)
        names = (REPORT_SIGNAL, FAILED_SIGNAL, STARTED_SIGNAL)
        return all(GObject.signal_lookup(name, source) for name in names)

    def _open_folders(self) -> None:
        """The empty state's action: the window's preferences on the folders entry."""
        self.page.activate_action(ACTION_FOLDERS, None)

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

    def _config(self) -> Any:
        config: Any = getattr(self._source, "config", None)
        return config() if callable(config) else None

    def _min_age_days(self) -> int:
        config = self._config()
        return config.devdirs_min_age_days if config is not None else DEVDIRS_MIN_AGE_DAYS

    def _roots_state(self) -> RootsState:
        """The saved folders from the service's config; a source without one has no notice."""
        config = self._config()
        if config is None:
            return RootsState()
        missing = config.missing_roots
        usable = len(config.devdirs_roots) > len(missing)
        shown = tuple(home_relative(path=path, home=Path.home()) for path in missing)
        return RootsState(missing=shown, usable=usable)

    def _saved_roots(self) -> tuple[Path, ...] | None:
        config = self._config()
        return config.devdirs_roots if config is not None else None

    def _on_report(self, *_args: object) -> None:
        report = getattr(self._source, "disk_report", lambda: None)()
        self._seen_roots = self._saved_roots()
        self._roots = self._roots_state()
        self.page.show_report(
            report=report,
            now=self._clock(),
            min_age_days=self._min_age_days(),
            roots=self._roots,
        )

    def _on_snapshot(self, *_args: object) -> None:
        """Preferences saved new folders: refresh the notice now, not at the next scan.

        Only the saved tuple is compared: probing the folders here would touch the disk at
        every tick, and a root on a stuck network mount would freeze the window.
        """
        if self._saved_roots() != self._seen_roots:
            self._on_report()

    def _on_started(self, *_args: object) -> None:
        self.page.begin_scan()

    def _on_failed(self, *_args: object) -> None:
        self.page.show_scan_failed()

    def close(self) -> None:
        """Drop the signal handlers; the source outlives the window."""
        for handler in self._handlers:
            self._source.disconnect(handler)
        self._handlers = []
