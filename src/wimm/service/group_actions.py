import logging
from collections.abc import Callable
from typing import Any

from wimm.model.enums import GroupId
from wimm.service.notifier import (
    ACTION_OPEN_GROUP,
    ACTION_SNOOZE_GROUP,
    APP_ACTION_PREFIX,
)

LOGGER = logging.getLogger(__name__)


def _open_group(application: Any, target: str) -> None:
    application._window_host.present(group_id=target or None)


def _snooze_group(application: Any, target: str) -> None:
    if application._notifications is None:
        LOGGER.warning("Snooze of %r ignored: notifications are not running", target)
        return
    application._notifications.snooze_group(group_id=GroupId(target))


def register_group_actions(*, application: Any) -> None:
    """Add ``open-group`` and ``snooze-group`` (string target, "" means no group).

    Notifications name these as ``app.*`` actions, so they work with the window closed.
    The handlers read the window host and the coordinator from the application when
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
