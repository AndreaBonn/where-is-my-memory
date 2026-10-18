import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from wimm.core.notify_types import NotificationIntent
from wimm.i18n import N_, _

if TYPE_CHECKING:
    from gi.repository import Gio

LOGGER = logging.getLogger(__name__)

APP_ACTION_PREFIX = "app."
ACTION_OPEN_GROUP = f"{APP_ACTION_PREFIX}open-group"
ACTION_SNOOZE_GROUP = f"{APP_ACTION_PREFIX}snooze-group"
# Both actions take a string target; "" means "show the window, no group". The
# notifier only names the actions: registering them is the application's job.
NO_GROUP_TARGET = ""
PRESSURE_ID_PREFIX = "pressure-"
OPEN_LABEL = N_("Vedi e decidi")
SNOOZE_LABEL = N_("Non ora (24 h)")


class NotifierPriority(Enum):
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class NotificationButton:
    label: str
    action: str
    target: str


@dataclass(frozen=True, slots=True)
class NotificationSpec:
    """Plain description of a notification, inspectable without a bus."""

    id: str
    title: str
    body: str
    priority: NotifierPriority
    default_action: str
    default_target: str
    buttons: tuple[NotificationButton, ...]


class NotificationSink(Protocol):
    """The slice of ``Gio.Application`` the notifier needs."""

    def send_notification(self, id: str | None, notification: Any) -> None: ...

    def withdraw_notification(self, id: str) -> None: ...


def build_spec(*, intent: NotificationIntent) -> NotificationSpec:
    """Map an intent to a spec; texts are passed through unchanged."""
    if intent.group_id is None:
        priority = (
            NotifierPriority.HIGH
            if intent.id.startswith(PRESSURE_ID_PREFIX)
            else NotifierPriority.NORMAL
        )
        return NotificationSpec(
            id=intent.id,
            title=intent.title,
            body=intent.body,
            priority=priority,
            default_action=ACTION_OPEN_GROUP,
            default_target=NO_GROUP_TARGET,
            buttons=(),
        )
    group_id = str(intent.group_id)
    return NotificationSpec(
        id=intent.id,
        title=intent.title,
        body=intent.body,
        priority=NotifierPriority.NORMAL,
        default_action=ACTION_OPEN_GROUP,
        default_target=group_id,
        buttons=(
            NotificationButton(label=_(OPEN_LABEL), action=ACTION_OPEN_GROUP, target=group_id),
            NotificationButton(label=_(SNOOZE_LABEL), action=ACTION_SNOOZE_GROUP, target=group_id),
        ),
    )


def to_gio_notification(*, spec: NotificationSpec) -> "Gio.Notification":
    """Build the ``Gio.Notification``; the body is set as plain text, never escaped."""
    from gi.repository import Gio, GLib

    notification = Gio.Notification.new(spec.title)
    notification.set_body(spec.body)
    notification.set_priority(
        Gio.NotificationPriority.HIGH
        if spec.priority is NotifierPriority.HIGH
        else Gio.NotificationPriority.NORMAL
    )
    notification.set_default_action_and_target(
        spec.default_action, GLib.Variant.new_string(spec.default_target)
    )
    for button in spec.buttons:
        notification.add_button_with_target(
            button.label, button.action, GLib.Variant.new_string(button.target)
        )
    return notification


class Notifier:
    """Sends intents through a sink; the same id replaces the previous notification (Gio)."""

    def __init__(self, *, sink: NotificationSink) -> None:
        self._sink = sink

    def notify(self, *, intents: tuple[NotificationIntent, ...]) -> None:
        for intent in intents:
            # One failing notification must not hold back the others nor be retried every
            # cycle around the hourly limit: it is logged and counted as sent.
            try:
                spec = build_spec(intent=intent)
                LOGGER.info("Sending notification %s", spec.id)
                self._sink.send_notification(spec.id, to_gio_notification(spec=spec))
            except Exception:
                LOGGER.exception("Cannot send notification %s", intent.id)

    def withdraw(self, *, id: str) -> None:
        self._sink.withdraw_notification(id)
