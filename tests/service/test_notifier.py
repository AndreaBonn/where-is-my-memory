from typing import Any

import pytest

from wimm.core.notify_types import NotificationIntent
from wimm.model.enums import GroupId
from wimm.service.notifier import (
    ACTION_OPEN_GROUP,
    ACTION_SNOOZE_GROUP,
    APP_ACTION_PREFIX,
    Notifier,
    NotifierPriority,
    build_spec,
    to_gio_notification,
)

GROUP = GroupId("whitebox")
IDLE = NotificationIntent(
    id="idle-whitebox",
    title="whitebox è inattivo da 2 h",
    body="1,1 GB <b>x</b> & co",
    group_id=GROUP,
)
AGGREGATE = NotificationIntent(
    id="idle-aggregate", title="4 gruppi inattivi", body="3,8 GB", group_id=None
)
PRESSURE = NotificationIntent(
    id="pressure-ram", title="RAM quasi esaurita (7% libera)", body="Liberabile", group_id=None
)


class FakeSink:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []
        self.withdrawn: list[str] = []

    def send_notification(self, id: str | None, notification: Any) -> None:
        self.sent.append((str(id), notification))

    def withdraw_notification(self, id: str) -> None:
        self.withdrawn.append(id)


def test_idle_spec_has_open_default_and_two_buttons_with_group_id() -> None:
    spec = build_spec(intent=IDLE)
    assert spec.default_action == ACTION_OPEN_GROUP == "app.open-group"
    assert spec.default_target == "whitebox"
    assert [(b.label, b.action, b.target) for b in spec.buttons] == [
        ("Vedi e decidi", "app.open-group", "whitebox"),
        ("Non ora (24 h)", "app.snooze-group", "whitebox"),
    ]
    assert spec.priority is NotifierPriority.NORMAL


def test_spec_keeps_texts_verbatim_without_markup_handling() -> None:
    spec = build_spec(intent=IDLE)
    assert (spec.id, spec.title, spec.body) == (IDLE.id, IDLE.title, IDLE.body)


@pytest.mark.parametrize("intent", [PRESSURE, AGGREGATE])
def test_groupless_intents_open_window_without_group_and_have_no_buttons(
    intent: NotificationIntent,
) -> None:
    spec = build_spec(intent=intent)
    assert (spec.default_action, spec.default_target) == (ACTION_OPEN_GROUP, "")
    assert spec.buttons == ()


def test_pressure_is_high_priority_and_has_no_snooze() -> None:
    spec = build_spec(intent=PRESSURE)
    assert spec.priority is NotifierPriority.HIGH
    assert all(b.action != ACTION_SNOOZE_GROUP for b in spec.buttons)
    assert build_spec(intent=AGGREGATE).priority is NotifierPriority.NORMAL


def test_only_the_two_documented_actions_are_used() -> None:
    used = set()
    for intent in (IDLE, AGGREGATE, PRESSURE):
        spec = build_spec(intent=intent)
        used.add(spec.default_action)
        used.update(b.action for b in spec.buttons)
    assert used == {"app.open-group", "app.snooze-group"}
    assert f"{APP_ACTION_PREFIX}snooze-group" == ACTION_SNOOZE_GROUP


def test_same_id_twice_sends_twice_with_same_id() -> None:
    sink = FakeSink()
    notifier = Notifier(sink=sink)
    notifier.notify(intents=(IDLE, IDLE))
    assert [sent_id for sent_id, _ in sink.sent] == ["idle-whitebox", "idle-whitebox"]


def test_notify_sends_one_gio_notification_per_intent() -> None:
    sink = FakeSink()
    Notifier(sink=sink).notify(intents=(IDLE, PRESSURE))
    assert [sent_id for sent_id, _ in sink.sent] == ["idle-whitebox", "pressure-ram"]


def test_withdraw_forwards_id() -> None:
    sink = FakeSink()
    Notifier(sink=sink).withdraw(id="idle-whitebox")
    assert sink.withdrawn == ["idle-whitebox"]


class RecordedNotification:
    """Stands in for Gio.Notification, which has no getters to read back."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.body: str | None = None
        self.priority: Any = None
        self.default: tuple[str, str] | None = None
        self.buttons: list[tuple[str, str, str]] = []

    @classmethod
    def new(cls, title: str) -> "RecordedNotification":
        return cls(title)

    def set_body(self, body: str) -> None:
        self.body = body

    def set_priority(self, priority: Any) -> None:
        self.priority = priority

    def set_default_action_and_target(self, action: str, target: Any) -> None:
        self.default = (action, target.get_string())

    def add_button_with_target(self, label: str, action: str, target: Any) -> None:
        self.buttons.append((label, action, target.get_string()))


def build_recorded(
    monkeypatch: pytest.MonkeyPatch, *, intent: NotificationIntent
) -> RecordedNotification:
    from gi.repository import Gio

    monkeypatch.setattr(Gio, "Notification", RecordedNotification)
    return to_gio_notification(spec=build_spec(intent=intent))  # type: ignore[return-value]


def test_pressure_gio_notification_is_high_priority_and_opens_the_window_without_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gi.repository import Gio

    notification = build_recorded(monkeypatch, intent=PRESSURE)

    assert notification.title == "RAM quasi esaurita (7% libera)"
    assert notification.body == "Liberabile"
    assert notification.priority == Gio.NotificationPriority.HIGH
    assert notification.default == ("app.open-group", "")
    assert notification.buttons == []


def test_idle_gio_notification_is_normal_priority_with_the_two_group_buttons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gi.repository import Gio

    notification = build_recorded(monkeypatch, intent=IDLE)

    assert notification.body == "1,1 GB <b>x</b> & co"  # plain text, never escaped
    assert notification.priority == Gio.NotificationPriority.NORMAL
    assert notification.default == ("app.open-group", "whitebox")
    assert notification.buttons == [
        ("Vedi e decidi", "app.open-group", "whitebox"),
        ("Non ora (24 h)", "app.snooze-group", "whitebox"),
    ]


def test_gio_notification_is_a_real_gio_notification_by_default() -> None:
    from gi.repository import Gio

    assert isinstance(to_gio_notification(spec=build_spec(intent=PRESSURE)), Gio.Notification)


class FirstFailsSink(FakeSink):
    def send_notification(self, id: str | None, notification: Any) -> None:
        if not self.sent and id == "idle-whitebox":
            self.sent.append(("failed", None))
            raise RuntimeError("bus gone")
        super().send_notification(id, notification)


def test_one_failing_notification_does_not_block_the_others() -> None:
    sink = FirstFailsSink()

    Notifier(sink=sink).notify(intents=(IDLE, PRESSURE))

    assert [sent_id for sent_id, _ in sink.sent] == ["failed", "pressure-ram"]
