from typing import Any

import pytest
from gi.repository import Gio, GLib

from wimm.app import create_application
from wimm.model.enums import GroupId
from wimm.service.group_actions import register_group_actions, register_monitor_action


class FakeHost:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def present(self, *, group_id: str | None) -> None:
        self.calls.append(group_id)


class FakeService:
    def __init__(self) -> None:
        self.snoozed: list[tuple[GroupId, float]] = []

    def snooze(self, *, group_id: GroupId, duration_s: float) -> None:
        self.snoozed.append((group_id, duration_s))


def make_application() -> Any:
    application: Any = Gio.Application(application_id="io.github.wimm.ActionsTest")
    application._window_host = FakeHost()
    application._service = FakeService()
    register_group_actions(application=application)
    return application


def activate(application: Any, name: str, target: str) -> None:
    application.lookup_action(name).activate(GLib.Variant.new_string(target))


def test_application_registers_quit_open_group_and_snooze_group() -> None:
    # list_actions() needs a registered application: the exact set is checked over D-Bus
    # in test_inspector_dbus.py. Here each name must resolve and an unknown one must not.
    application = create_application()
    for name in ("quit", "open-group", "snooze-group"):
        assert application.lookup_action(name) is not None
    assert application.lookup_action("snooze-all") is None


@pytest.mark.parametrize(("target", "expected"), [("", None), ("g_1", "g_1")])
def test_open_group_presents_the_window_on_the_group_or_without_one(
    target: str, expected: str | None
) -> None:
    application = make_application()
    activate(application, "open-group", target)
    assert application._window_host.calls == [expected]
    assert application._service.snoozed == []


def test_snooze_group_asks_the_service_for_24_hours() -> None:
    application = make_application()
    activate(application, "snooze-group", "g_1")
    assert application._service.snoozed == [(GroupId("g_1"), 24 * 3600)]
    assert application._window_host.calls == []


def test_snooze_before_startup_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    application = make_application()
    application._service = None
    activate(application, "snooze-group", "g_1")
    assert "Snooze of 'g_1' ignored" in caplog.text


def test_snooze_with_an_empty_target_is_logged_and_snoozes_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = make_application()
    activate(application, "snooze-group", "")
    assert application._service.snoozed == []
    assert "Snooze of '' ignored" in caplog.text


def test_actions_require_a_string_parameter() -> None:
    application = make_application()
    parameter_type = application.lookup_action("open-group").get_parameter_type()
    assert parameter_type.dup_string() == "s"


class RetryService:
    def __init__(self) -> None:
        self.retries = 0

    def retry_now(self) -> None:
        self.retries += 1


def test_restart_monitor_is_registered_and_asks_the_service_to_retry() -> None:
    assert create_application().lookup_action("restart-monitor") is not None
    application: Any = Gio.Application(application_id="io.github.wimm.RetryTest")
    application._service = RetryService()
    register_monitor_action(application=application)

    application.lookup_action("restart-monitor").activate(None)

    assert application._service.retries == 1


def test_restart_monitor_without_a_service_only_logs(caplog: pytest.LogCaptureFixture) -> None:
    application: Any = Gio.Application(application_id="io.github.wimm.RetryTest2")
    application._service = None
    register_monitor_action(application=application)

    application.lookup_action("restart-monitor").activate(None)

    assert "Retry ignored" in caplog.text
