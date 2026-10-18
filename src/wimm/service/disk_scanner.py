"""The disk scan (SPECIFICHE 6.3, 7.6): Docker usage, caches and development folders.

``RealDiskScanner.scan`` is blocking and not thread-safe (the directory size cache is one
file), so ``AppService`` calls it only from its dedicated disk worker.
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from wimm.collectors import CollectorResult
from wimm.collectors.caches import collect_caches
from wimm.collectors.devdirs import DevDirSettings, scan_devdirs
from wimm.collectors.disk_report import DockerDiskSource
from wimm.config import Config
from wimm.core.disk_rules import build_disk_report, filter_devdirs
from wimm.model.disk import DiskReport, DockerDisk
from wimm.service.sampler import wall_clock
from wimm.service.sampler_environment import resolve_cache_table

LOGGER = logging.getLogger(__name__)


class ScanCancelled(Exception):
    """The scan stopped because the application is quitting."""


class DiskScanner(Protocol):
    def scan(self, *, config: Config) -> DiskReport: ...

    def cancel(self) -> None: ...


class DockerSource(Protocol):
    def collect(self) -> CollectorResult[DockerDisk]: ...


class RealDiskScanner:
    """Scans with the collectors; ``config`` is read at each scan, so edits apply to the next."""

    def __init__(
        self,
        *,
        docker: DockerSource,
        home: Path,
        cache_dir: Path,
        clock: Callable[[], datetime] = wall_clock,
    ) -> None:
        self._docker = docker
        self._home = home
        self._cache_dir = cache_dir
        self._clock = clock
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Stop a running scan at its next pause; any thread may call it, once is enough.

        Without it, quitting during a scan of a large home would keep the process alive
        until the scan ends, since the worker thread is joined at interpreter exit.
        """
        self._cancelled.set()

    def _pause(self, seconds: float) -> None:
        self._check()
        time.sleep(seconds)

    def _check(self) -> None:
        if self._cancelled.is_set():
            raise ScanCancelled

    def scan(self, *, config: Config) -> DiskReport:
        """Run the three scans in sequence and assemble the report.

        Docker being unreachable is not an error: the report carries it as unavailable.
        Folders the collectors cannot read are skipped and counted.
        """
        started = self._clock()
        docker = self._docker.collect().data
        self._check()
        table = resolve_cache_table(home=self._home, roots=config.devdirs_roots)
        caches = collect_caches(table=table, cache_dir=self._cache_dir, sleep=self._pause)
        self._check()
        settings = DevDirSettings(
            roots=config.admitted_roots, home=self._home, max_depth=config.devdirs_max_depth
        )
        found = scan_devdirs(
            settings=settings, cache_dir=self._cache_dir, now=started.timestamp(), sleep=self._pause
        )
        if found.error_count:
            LOGGER.info("Development folder scan skipped %d unreadable entries", found.error_count)
        devdirs = filter_devdirs(candidates=found.devdirs, min_age_days=config.devdirs_min_age_days)
        return build_disk_report(scanned_at=started, docker=docker, caches=caches, devdirs=devdirs)


def build_disk_scanner(*, home: Path, cache_dir: Path) -> RealDiskScanner:
    """The scanner with the real Docker reader, for the running application."""
    return RealDiskScanner(docker=DockerDiskSource(), home=home, cache_dir=cache_dir)
