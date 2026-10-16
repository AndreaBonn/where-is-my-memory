import logging
from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from wimm.tray.status_notifier import WATCHER_NAME

LOGGER = logging.getLogger(__name__)
WATCHER_ABSENT_MS = 10_000


@dataclass(frozen=True)
class WatcherCallbacks:
    """What the watcher tells its owner; each runs on the main loop."""

    on_appeared: Callable[[], None]
    on_absent: Callable[[], None]


class TrayWatcher:
    """Follow org.kde.StatusNotifierWatcher: register on every appearance, flag a missing host."""

    def __init__(
        self,
        *,
        connection: Gio.DBusConnection,
        callbacks: WatcherCallbacks,
        absent_after_ms: int = WATCHER_ABSENT_MS,
    ) -> None:
        self._callbacks = callbacks
        self._seen = False
        self._timer = GLib.timeout_add(absent_after_ms, self._timed_out)
        self._watch = Gio.bus_watch_name_on_connection(
            connection,
            WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._appeared,
            self._vanished,
        )

    def close(self) -> None:
        if self._watch:
            Gio.bus_unwatch_name(self._watch)
            self._watch = 0
        self._stop_timer()

    def _stop_timer(self) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _appeared(self, _connection: Gio.DBusConnection, _name: str, _owner: str) -> None:
        self._seen = True
        self._stop_timer()
        self._notify(self._callbacks.on_appeared)

    def _vanished(self, _connection: Gio.DBusConnection, _name: str) -> None:
        LOGGER.info("StatusNotifierWatcher is not on the bus")

    def _timed_out(self) -> bool:
        self._timer = 0
        if not self._seen:
            self._notify(self._callbacks.on_absent)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _notify(callback: Callable[[], None]) -> None:
        # A GLib callback would only print the traceback to stderr: log it instead.
        try:
            callback()
        except Exception:
            LOGGER.exception("Watcher callback failed")
