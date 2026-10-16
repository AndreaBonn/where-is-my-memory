import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ClassVar, Protocol

from gi.repository import GLib, GObject

from wimm.config import Config
from wimm.model.snapshot import Snapshot

LOGGER = logging.getLogger(__name__)


class CycleSampler(Protocol):
    def run_cycle(self) -> Snapshot: ...


class AppService(GObject.Object):
    __gsignals__: ClassVar = {"snapshot-updated": (GObject.SignalFlags.RUN_LAST, None, ())}

    def __init__(self, *, sampler: CycleSampler, config: Config) -> None:
        super().__init__()
        self._sampler = sampler
        self._config = config
        self._snapshot: Snapshot | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wimm-sampler")
        self._timer = 0
        self._busy = False
        self._stopped = False
        self.consecutive_failures = 0

    def snapshot(self) -> Snapshot | None:
        return self._snapshot

    def config(self) -> Config:
        return self._config

    def start(self) -> None:
        if self._timer or self._stopped:
            return
        self._timer = GLib.timeout_add_seconds(self._config.sample_interval_s, self.request_cycle)
        self.request_cycle()

    def request_cycle(self) -> bool:
        if not self._busy and not self._stopped:
            self._busy = True
            future = self._executor.submit(self._sampler.run_cycle)
            future.add_done_callback(self._completed)
        return GLib.SOURCE_CONTINUE

    def _completed(self, future: Future[Snapshot]) -> None:
        GLib.idle_add(self._publish, future)

    def _publish(self, future: Future[Snapshot]) -> bool:
        self._busy = False
        if self._stopped:
            return GLib.SOURCE_REMOVE
        try:
            snapshot = future.result()
        except Exception:
            self.consecutive_failures += 1
            LOGGER.exception("Sampling failed (%d consecutive cycles)", self.consecutive_failures)
        else:
            self._snapshot = snapshot
            self.consecutive_failures = 0
            self.emit("snapshot-updated")
        return GLib.SOURCE_REMOVE

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self._executor.shutdown(wait=True, cancel_futures=True)
