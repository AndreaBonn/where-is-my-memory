import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from gi.repository import Gio

from wimm.model.snapshot import Snapshot
from wimm.tray.dbus_menu import DBusMenu
from wimm.tray.menu_model import (
    CALLBACK_MUTE,
    CALLBACK_OPEN,
    CALLBACK_QUIT,
    build_menu,
    parse_group_callback,
    tray_icon,
    tray_label,
    tray_tooltip,
)
from wimm.tray.status_notifier import StatusNotifierItem
from wimm.tray.watcher import TrayWatcher, WatcherCallbacks

LOGGER = logging.getLogger(__name__)
TITLE = "Where Is My Memory"
MUTE_DURATION_S = 3600


class TrayService(Protocol):
    """The part of AppService the tray reads and drives."""

    @property
    def consecutive_failures(self) -> int: ...

    @property
    def notifications_muted_until(self) -> datetime | None: ...

    def snapshot(self) -> Snapshot | None: ...

    def mute_notifications(self, *, duration_s: float) -> None: ...

    def connect(self, detailed_signal: str, handler: Callable[..., Any]) -> int: ...

    def disconnect(self, handler_id: int) -> None: ...


class Tray:
    """The status icon and its menu, kept in step with the service."""

    def __init__(
        self,
        *,
        connection: Gio.DBusConnection,
        service: TrayService,
        on_open: Callable[[str | None], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._connection = connection
        self._service, self._on_open, self._on_quit = service, on_open, on_quit
        self._watcher: TrayWatcher | None = None
        self._reported_missing = False
        self._item = StatusNotifierItem(
            connection=connection,
            on_activate=lambda: on_open(None),
            on_secondary_activate=lambda: on_open(None),
            title=TITLE,
        )
        self._menu = DBusMenu(connection=connection, on_click=self._clicked)
        self._handlers = [
            service.connect(signal, self._refresh_from_signal)
            for signal in ("snapshot-updated", "cycle-failed")
        ]
        try:
            self.refresh()
        except Exception:
            # Nobody holds a half-built tray, so nobody else could release what it exported.
            self.close()
            raise

    def start(self, *, on_missing: Callable[[bool], None] | None = None) -> None:
        """Register with the watcher now and at every reappearance (shell restart).

        ``on_missing(True)`` fires when no watcher shows up in time, ``on_missing(False)``
        when one appears afterwards.
        """
        if self._watcher is not None:
            return
        notify = on_missing or (lambda _missing: None)
        self._reported_missing = False

        def absent() -> None:
            self._reported_missing = True
            notify(True)

        def registered(succeeded: bool) -> None:
            # The banner goes only once the icon is really registered, not when the watcher shows.
            if succeeded and self._reported_missing:
                self._reported_missing = False
                notify(False)

        self._watcher = TrayWatcher(
            connection=self._connection,
            callbacks=WatcherCallbacks(
                on_appeared=lambda: self._item.register_with_watcher(on_done=registered),
                on_absent=absent,
            ),
        )

    def refresh(self) -> None:
        snapshot = self._service.snapshot()
        failures = self._service.consecutive_failures
        self._item.icon_name = tray_icon(snapshot=snapshot, consecutive_failures=failures)
        self._item.tooltip = tray_tooltip(snapshot=snapshot)
        self._item.label = tray_label(snapshot=snapshot)
        self._menu.set_items(
            build_menu(
                snapshot=snapshot,
                consecutive_failures=failures,
                muted_until=self._service.notifications_muted_until,
            )
        )

    def close(self) -> None:
        for handler in self._handlers:
            self._service.disconnect(handler)
        self._handlers = []
        if self._watcher is not None:
            self._watcher.close()
            self._watcher = None
        self._menu.close()
        self._item.close()

    def _refresh_from_signal(self, *_args: object) -> None:
        # A GObject handler would only print the traceback to stderr: log it instead.
        try:
            self.refresh()
        except Exception:
            LOGGER.exception("Tray refresh failed")

    def _clicked(self, callback_id: str) -> None:
        if callback_id == CALLBACK_OPEN:
            self._on_open(None)
        elif callback_id == CALLBACK_QUIT:
            self._on_quit()
        elif callback_id == CALLBACK_MUTE:
            self._service.mute_notifications(duration_s=MUTE_DURATION_S)
            self._refresh_from_signal()
        elif (group_id := parse_group_callback(callback_id=callback_id)) is not None:
            self._on_open(group_id)
        else:
            LOGGER.warning("Unknown menu callback %s", callback_id)
