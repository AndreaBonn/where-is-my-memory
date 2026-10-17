import logging
from collections.abc import Callable
from typing import Any

from wimm.model.enums import GroupId
from wimm.service.notifier import (
    ACTION_OPEN_GROUP,
    ACTION_SNOOZE_GROUP,
    APP_ACTION_PREFIX,
)
from wimm.service.user_state import SNOOZE_GROUP_S

LOGGER = logging.getLogger(__name__)
RESTART_MONITOR_ACTION = "restart-monitor"


def _open_group(application: Any, target: str) -> None:
    application._window_host.present(group_id=target or None)


def _snooze_group(application: Any, target: str) -> None:
    if application._service is None or not target:
        LOGGER.warning("Snooze of %r ignored: no service or no target", target)
        return
    application._service.snooze(group_id=GroupId(target), duration_s=SNOOZE_GROUP_S)


def register_group_actions(*, application: Any) -> None:
    """Add ``open-group`` and ``snooze-group`` (string target, "" means no group).

    Notifications name these as ``app.*`` actions, so they work with the window closed.
    The handlers read the window host and the service from the application when
    activated: both exist only after startup, and GTK stays unloaded until a window opens.
    """
    from gi.repository import Gio, GLib

    handlers: dict[str, Callable[[Any, str], None]] = {
        ACTION_OPEN_GROUP: _open_group,
        ACTION_SNOOZE_GROUP: _snooze_group,
    }
    for qualified, handler in handlers.items():
        action = Gio.SimpleAction.new(
            name=qualified.removeprefix(APP_ACTION_PREFIX),
            parameter_type=GLib.VariantType.new("s"),
        )
        action.connect(
            "activate", lambda _a, parameter, h=handler: h(application, parameter.get_string())
        )
        application.add_action(action=action)


def register_monitor_action(*, application: Any) -> None:
    """A2: ``app.restart-monitor`` asks the service to read the system again at once.

    The error page's "Riprova adesso" names it; before this action existed GTK kept
    that button disabled forever.
    """
    from gi.repository import Gio

    def retry(*_args: object) -> None:
        if application._service is None:
            LOGGER.warning("Retry ignored: no service")
            return
        application._service.retry_now()

    action = Gio.SimpleAction.new(name=RESTART_MONITOR_ACTION, parameter_type=None)
    action.connect("activate", retry)
    application.add_action(action=action)
