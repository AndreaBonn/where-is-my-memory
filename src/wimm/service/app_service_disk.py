"""The disk scan on AppService: a second worker, a timer, a coalesced rescan."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from gi.repository import GLib

from wimm.config import Config
from wimm.core import constants as c
from wimm.core.disk_rules import safe_reclaimable_bytes
from wimm.model.actions import Plan
from wimm.model.disk import DiskReport
from wimm.service.actions import DISK_REQUEST_KINDS
from wimm.service.disk_scanner import DiskScanner

LOGGER = logging.getLogger(__name__)
MS_PER_S = 1000


class DiskMixin:
    """Main loop side of the disk scan; the scan itself runs on one dedicated worker.

    The scan never shares the sampling worker (it takes minutes on a large home) and never
    the main loop. Mixed into ``AppService``, which provides the attributes declared here.
    """

    _executor: ThreadPoolExecutor
    _sampler: Any
    _config: Config
    _stopped: bool

    if TYPE_CHECKING:

        def emit(self, signal_name: str, *args: Any) -> None: ...

        def request_cycle(self) -> bool: ...

    def _init_disk(self) -> None:
        self._disk_scanner: DiskScanner | None = None
        self._disk_start_delay_s: float = c.DISK_SCAN_START_DELAY_S
        self._disk_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wimm-disk")
        self._disk_report: DiskReport | None = None
        self._disk_timer = 0
        self._disk_start_timer = 0
        self._disk_busy = False
        self._disk_pending = False
        self._disk_plan_ids: set[str] = set()

    def attach_disk_scanner(
        self, *, scanner: DiskScanner, start_delay_s: float = c.DISK_SCAN_START_DELAY_S
    ) -> None:
        """Scan with ``scanner`` after ``start_delay_s`` and every configured interval.

        Call before ``start``.
        """
        self._disk_scanner = scanner
        self._disk_start_delay_s = start_delay_s

    def disk_report(self) -> DiskReport | None:
        """The latest completed scan, or None before the first one."""
        return self._disk_report

    def rescan_disk(self) -> None:
        """Scan now; a request during a running scan schedules one more run after it."""
        if self._disk_scanner is None or self._stopped:
            return
        self._disk_pending = self._disk_busy
        if not self._disk_busy:
            self._disk_busy = True
            future = self._disk_executor.submit(self._disk_scanner.scan, config=self._config)
            future.add_done_callback(self._disk_completed)
            self.emit("disk-scan-started")

    def disk_scanning(self) -> bool:
        """A scan is running; a window opened now shows it as in progress."""
        return self._disk_busy

    def _track_disk_plan(self, *, plan: Plan) -> None:
        """Remember a plan that changes the disk, so its end triggers a rescan."""
        if plan.request.kind in DISK_REQUEST_KINDS:
            self._disk_plan_ids.add(plan.plan_id)

    def _after_action(self, *, plan_id: str, ran: bool) -> None:
        """Rescan once a disk plan ran, so the view and `reclaimable_now.disk` follow it."""
        if plan_id in self._disk_plan_ids:
            self._disk_plan_ids.discard(plan_id)
            if ran:
                self.rescan_disk()

    def _disk_tick(self) -> bool:
        self.rescan_disk()
        return GLib.SOURCE_CONTINUE

    def _start_disk(self) -> None:
        if self._disk_scanner is not None and not self._disk_start_timer:
            delay_ms = round(self._disk_start_delay_s * MS_PER_S)
            self._disk_start_timer = GLib.timeout_add(delay_ms, self._first_disk_scan)

    def _first_disk_scan(self) -> bool:
        self._disk_start_timer = 0
        self._disk_timer = GLib.timeout_add_seconds(
            self._config.disk_scan_interval_s, self._disk_tick
        )
        self.rescan_disk()
        return GLib.SOURCE_REMOVE

    def _reschedule_disk_timer(self) -> None:
        """A new interval applies from now; before the first scan the start delay stands."""
        if self._disk_timer:
            GLib.source_remove(self._disk_timer)
            self._disk_timer = GLib.timeout_add_seconds(
                self._config.disk_scan_interval_s, self._disk_tick
            )

    def _disk_completed(self, future: Future[DiskReport]) -> None:
        GLib.idle_add(self._disk_publish, future)

    def _disk_publish(self, future: Future[DiskReport]) -> bool:
        self._disk_busy = False
        if self._stopped:
            return GLib.SOURCE_REMOVE
        try:
            report = future.result()
        except Exception:
            # The previous report stays: a stale list beats an empty one.
            LOGGER.exception("Disk scan failed")
            self.emit("disk-scan-failed")
        else:
            self._disk_report = report
            self._publish_reclaimable(report=report)
            self.emit("disk-report-updated")
        if self._disk_pending:
            self.rescan_disk()
        return GLib.SOURCE_REMOVE

    def _publish_reclaimable(self, *, report: DiskReport) -> None:
        """Hand the safe total to the sampler on its worker, then sample so it shows."""
        total = safe_reclaimable_bytes(report=report)
        self._executor.submit(self._sampler.apply_reclaimable_disk, reclaimable_disk=total)
        self.request_cycle()

    def _stop_disk(self) -> None:
        for source in (self._disk_start_timer, self._disk_timer):
            if source:
                GLib.source_remove(source)
        self._disk_start_timer = self._disk_timer = 0
        if self._disk_scanner is not None:
            self._disk_scanner.cancel()
        self._disk_executor.shutdown(wait=False, cancel_futures=True)
