"""The flag toggles in the preferences switch the whole window without a restart."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from gi.repository import Adw, Gio

from tests.ui.conftest import WindowFactory, main_context_iterate, present_and_settle
from tests.ui.fakes import FakeActionService
from wimm import i18n
from wimm.app import WindowHost
from wimm.config import Config
from wimm.language_switch import register_language_action
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog
from wimm.ui.window import MainWindow
from wimm.ui.window_preferences import PreferencesEnv, install_preferences

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("english_catalog")]


class SwitchingService(FakeActionService):
    retries = 0

    def retry_now(self) -> None:
        self.retries += 1


@dataclass
class AppShell:
    """What switch_language reads from the application, around the real Gio.Application."""

    application: Gio.Application
    _window_host: WindowHost
    _service: SwitchingService
    _tray: None = None


@dataclass
class Shell:
    host: WindowHost
    service: SwitchingService

    def window(self) -> MainWindow:
        window = self.host._window
        assert isinstance(window, MainWindow)
        return window

    def preferences(self) -> PreferencesDialog:
        dialog = self.window().get_visible_dialog()
        assert isinstance(dialog, PreferencesDialog)
        return dialog


@pytest.fixture
def shell(
    application: Gio.Application, window_factory: WindowFactory, snapshot: Snapshot, tmp_path: Path
) -> Iterator[Shell]:
    service = SwitchingService(snapshot=snapshot, config=Config())
    env = PreferencesEnv(
        paths=UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path),
        home=tmp_path,
    )

    def build() -> MainWindow:
        window = window_factory(service)
        install_preferences(window=window, source=service, env=env)
        register_language_action(actions=window.window_actions, application=shell)
        return window

    host = WindowHost(factory=build)
    shell = AppShell(application=application, _window_host=host, _service=service)
    yield Shell(host=host, service=service)


def open_preferences(shell: Shell) -> PreferencesDialog:
    shell.host.present(group_id=None)
    present_and_settle(shell.window())
    shell.window().activate_action("win.preferences", None)
    main_context_iterate()
    return shell.preferences()


def page_titles(window: MainWindow) -> set[str | None]:
    pages = cast(Gio.ListModel, window.view_stack.get_pages())
    items = (cast(Adw.ViewStackPage, pages.get_item(i)) for i in range(pages.get_n_items()))
    return {item.get_title() for item in items}


def test_the_selector_shows_two_flags_with_the_active_language_pressed(shell: Shell) -> None:
    dialog = open_preferences(shell)

    italian, english = dialog.language.buttons["it"], dialog.language.buttons["en"]
    assert (italian.get_label(), english.get_label()) == ("🇮🇹", "🇺🇸")
    assert (italian.get_tooltip_text(), english.get_tooltip_text()) == ("Italiano", "English")
    assert italian.get_active() and not english.get_active()
    assert dialog.language.group.get_title() == "Lingua"
    assert dialog.language.row.get_title() == "Italiano"


def test_choosing_the_us_flag_rebuilds_the_window_in_english(shell: Shell) -> None:
    dialog = open_preferences(shell)
    old = shell.window()
    assert "Panoramica" in page_titles(old)

    dialog.language.buttons["en"].set_active(True)
    main_context_iterate()

    assert i18n.current_language() == i18n.ENGLISH
    assert shell.service.config_updates == [{"language": "en"}]
    assert shell.service.retries == 1
    new = shell.window()
    assert new is not old and new.get_visible()
    assert "Overview" in page_titles(new)
    reopened = shell.preferences()
    assert reopened.get_title() == "Preferences"
    assert reopened.language.group.get_title() == "Language"
    assert reopened.language.buttons["en"].get_active()
    assert reopened.language.row.get_title() == "English"


def test_the_italian_flag_brings_the_window_back(shell: Shell) -> None:
    open_preferences(shell).language.buttons["en"].set_active(True)
    main_context_iterate()

    shell.preferences().language.buttons["it"].set_active(True)
    main_context_iterate()

    assert i18n.current_language() == i18n.ITALIAN
    assert "Panoramica" in page_titles(shell.window())
    assert shell.preferences().get_title() == "Preferenze"


def test_without_the_window_action_the_toggle_goes_back(
    display: None, snapshot: Snapshot, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A dialog outside the main window: nobody handles win.set-language.
    service = SwitchingService(snapshot=snapshot, config=Config())
    paths = UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path)
    dialog = PreferencesDialog(source=service, paths=paths, home=tmp_path)

    dialog.language.buttons["en"].set_active(True)

    assert i18n.current_language() == i18n.ITALIAN
    assert dialog.language.buttons["it"].get_active()
    assert not dialog.language.buttons["en"].get_active()
    assert "set-language" in caplog.text
