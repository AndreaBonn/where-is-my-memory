from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from gi.repository import GLib

from tests.test_cli import RecordingWindow
from wimm import i18n, language_switch
from wimm.app import WindowHost
from wimm.language_switch import switch_language


class SwitchWindow(RecordingWindow):
    def __init__(self, *, visible: bool = True) -> None:
        super().__init__()
        self.visible, self.saved, self.destroyed = visible, 0, False
        self.actions: list[str] = []

    def get_visible(self) -> bool:
        return self.visible

    def save_size(self) -> None:
        self.saved += 1

    def destroy(self) -> None:
        self.destroyed = True

    def activate_action(self, name: str, args: object) -> bool:
        self.actions.append(name)
        return True


class FakeService:
    def __init__(self, *, fail: bool = False) -> None:
        self.changes: list[Mapping[str, object]] = []
        self.retries = 0
        self.error: Exception | None = OSError("read-only") if fail else None

    def update_config(self, *, changes: Mapping[str, object], paths: Any, home: Path) -> Any:
        if self.error is not None:
            raise self.error
        self.changes.append(changes)

    def retry_now(self) -> None:
        self.retries += 1


class FakeTray:
    def __init__(self) -> None:
        self.refreshed = 0

    def refresh(self) -> None:
        self.refreshed += 1


class FakeApplication:
    def __init__(self, *, host: WindowHost, service: FakeService | None) -> None:
        self._window_host, self._service, self._tray = host, service, FakeTray()


def make_host(*, visible: bool = True) -> tuple[WindowHost, list[SwitchWindow]]:
    built: list[SwitchWindow] = []

    def factory() -> SwitchWindow:
        built.append(SwitchWindow(visible=visible))
        return built[-1]

    return WindowHost(factory=factory), built


def run_idle() -> None:
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


@pytest.mark.usefixtures("english_catalog")
def test_switch_saves_applies_and_rebuilds_the_open_window() -> None:
    host, built = make_host()
    host.present(group_id=None)
    application = FakeApplication(host=host, service=FakeService())

    switch_language(application=application, language=i18n.ENGLISH)

    assert i18n.current_language() == i18n.ENGLISH
    assert i18n._("Esci") == "Quit"
    assert application._service is not None
    assert application._service.changes == [{"language": "en"}]
    run_idle()
    old, new = built
    assert old.destroyed and old.saved == 1
    assert new.shown == [None] and not new.destroyed
    assert new.actions == ["win.preferences"]
    assert application._tray.refreshed == 1
    assert application._service.retries == 1


def test_switch_waits_for_the_idle_before_touching_the_window() -> None:
    # The toggle that asked for the switch lives in that window: never destroy it mid-signal.
    host, built = make_host()
    host.present(group_id=None)

    switch_language(application=FakeApplication(host=host, service=FakeService()), language="en")

    assert len(built) == 1 and not built[0].destroyed
    run_idle()
    assert built[0].destroyed


def test_a_hidden_window_is_dropped_and_built_again_only_when_shown() -> None:
    host, built = make_host(visible=False)
    host.present(group_id=None)

    switch_language(application=FakeApplication(host=host, service=FakeService()), language="en")
    run_idle()

    assert len(built) == 1 and built[0].destroyed
    host.present(group_id="g")
    assert len(built) == 2 and built[1].shown == ["g"]


def test_switch_without_a_window_still_refreshes_tray_and_sample() -> None:
    host, built = make_host()
    application = FakeApplication(host=host, service=FakeService())

    switch_language(application=application, language="en")
    run_idle()

    assert built == []
    assert application._tray.refreshed == 1


def test_switch_to_the_active_language_does_nothing() -> None:
    host, built = make_host()
    host.present(group_id=None)
    application = FakeApplication(host=host, service=FakeService())

    switch_language(application=application, language=i18n.ITALIAN)
    run_idle()

    assert application._service is not None and application._service.changes == []
    assert len(built) == 1 and not built[0].destroyed


def test_switch_to_an_unknown_language_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    application = FakeApplication(host=make_host()[0], service=FakeService())

    switch_language(application=application, language="fr")

    assert i18n.current_language() == i18n.ITALIAN
    assert "fr" in caplog.text


def test_a_failed_save_still_switches_for_this_session(caplog: pytest.LogCaptureFixture) -> None:
    application = FakeApplication(host=make_host()[0], service=FakeService(fail=True))

    switch_language(application=application, language="en")

    assert i18n.current_language() == i18n.ENGLISH
    assert "Cannot save" in caplog.text


@pytest.mark.usefixtures("english_catalog")
def test_the_registered_action_switches_with_its_string_parameter() -> None:
    from gi.repository import Gio

    from wimm.language_switch import register_language_action

    actions = Gio.SimpleActionGroup()
    application = FakeApplication(host=make_host()[0], service=FakeService())
    register_language_action(actions=actions, application=application)

    actions.activate_action("set-language", GLib.Variant("s", "en"))

    assert i18n.current_language() == i18n.ENGLISH


def test_toggles_before_the_idle_rebuild_the_window_once() -> None:
    host, built = make_host()
    host.present(group_id=None)
    application = FakeApplication(host=host, service=FakeService())

    switch_language(application=application, language="en")
    switch_language(application=application, language="it")
    run_idle()

    assert len(built) == 2 and built[0].destroyed and not built[1].destroyed
    assert application._service is not None and application._service.retries == 1


def test_a_service_error_on_save_still_switches(caplog: pytest.LogCaptureFixture) -> None:
    from wimm.model.errors import InvalidRequest

    service = FakeService()
    service.error = InvalidRequest()
    application = FakeApplication(host=make_host()[0], service=service)

    switch_language(application=application, language="en")

    assert i18n.current_language() == i18n.ENGLISH
    assert "Cannot save" in caplog.text


def test_a_failing_rebuild_still_asks_for_a_new_sample() -> None:
    host, _ = make_host()
    application = FakeApplication(host=host, service=FakeService())

    def broken(**_options: object) -> None:
        raise RuntimeError("rebuild failed")

    host.rebuild = broken  # type: ignore[method-assign]
    # Called directly: GLib only prints an exception raised inside an idle callback.
    with pytest.raises(RuntimeError):
        language_switch._refresh_views(application)

    assert application._service is not None and application._service.retries == 1
