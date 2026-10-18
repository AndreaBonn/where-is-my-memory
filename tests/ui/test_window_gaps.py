"""Window gaps: state saving failures, delayed save, about dialog, folders and preferences."""

import json
import logging
import os
from dataclasses import replace
from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import report
from tests.ui.conftest import (
    FakeActionService,
    FakeSource,
    WindowFactory,
    main_context_iterate,
    present_and_settle,
    wait_until,
)
from tests.ui.test_disk_roots import CHOOSE, ConfigSource, button
from wimm import __version__
from wimm.config import Config
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog
from wimm.ui.window_disk import DiskBinding
from wimm.ui.window_preferences import PreferencesEnv, install_preferences
from wimm.ui.window_state import STATE_FILE, save_window_size

pytestmark = pytest.mark.ui
SAVE_FAILED = "Could not save window state"


def test_saving_under_a_file_logs_and_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    path = blocker / STATE_FILE

    with caplog.at_level(logging.WARNING):
        save_window_size(path=path, width=800, height=600)

    assert [r.getMessage() for r in caplog.records if SAVE_FAILED in r.getMessage()] != []
    assert blocker.read_text() == "not a directory"
    # Paired positive: a usable location is written.
    good = tmp_path / "ok" / STATE_FILE
    save_window_size(path=good, width=800, height=600)
    assert json.loads(good.read_text()) == {"width": 800, "height": 600}


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_saving_where_the_directory_cannot_be_created_logs_and_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state = tmp_path / "locked"
    state.mkdir()
    state.chmod(0o500)
    try:
        with caplog.at_level(logging.WARNING):
            save_window_size(path=state / "sub" / STATE_FILE, width=800, height=600)
    finally:
        state.chmod(0o700)

    assert any(SAVE_FAILED in r.getMessage() for r in caplog.records)
    assert not (state / "sub").exists()


def test_a_resize_is_saved_later_without_closing_the_window(
    window_factory: WindowFactory, snapshot: Snapshot, tmp_path: Path
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    saved = tmp_path / "state" / STATE_FILE

    window.set_default_size(777, 555)
    # The save is debounced in real time (SAVE_DELAY_MS): wait for the file itself.
    wait_until(
        lambda: saved.exists() and json.loads(saved.read_text()) == {"width": 777, "height": 555},
        description="debounced window.json",
    )


def test_unset_default_size_saves_the_allocated_size(
    window_factory: WindowFactory,
    snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    window.present()
    wait_until(lambda: window.get_width() > 0, description="first layout")

    # GTK reports the size in use as the default once mapped: simulate "never set".
    with monkeypatch.context() as patch:
        patch.setattr(window, "get_default_size", lambda: (-1, -1))
        window.save_size()

    saved = json.loads((tmp_path / "state" / STATE_FILE).read_text())
    assert saved == {"width": window.get_width(), "height": window.get_height()}
    assert saved["width"] > 0
    assert saved["height"] > 0


def test_about_opens_a_dialog_with_the_version(
    window_factory: WindowFactory, snapshot: Snapshot
) -> None:
    window = window_factory(FakeSource(snapshot=snapshot))
    present_and_settle(window)

    window.activate_action("win.about", None)

    wait_until(lambda: window.get_visible_dialog() is not None, description="about dialog")
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AboutDialog)
    assert dialog.get_version() == __version__
    assert dialog.get_version() != ""


def test_empty_state_choose_folder_opens_the_folders_preferences(
    display: None, snapshot: Snapshot
) -> None:
    from gi.repository import Gio

    opened: list[str] = []
    group = Gio.SimpleActionGroup()
    action = Gio.SimpleAction.new("preferences-folders", None)
    action.connect("activate", lambda *_a: opened.append("folders"))
    group.add_action(action)
    source = ConfigSource(snapshot=snapshot, config=Config(devdirs_roots=()), report_=report())
    binding = DiskBinding(source=source, clock=lambda: snapshot.taken_at)
    window = Gtk.Window(child=binding.page)
    window.insert_action_group("win", group)
    choose = button(binding.page, CHOOSE)
    assert choose is not None

    choose.emit("clicked")

    assert opened == ["folders"]


def test_a_second_preferences_request_reuses_the_visible_dialog(
    window_factory: WindowFactory, snapshot: Snapshot, tmp_path: Path
) -> None:
    config = replace(Config(), devdirs_roots=(tmp_path,))
    service = FakeActionService(snapshot=snapshot, config=config)
    paths = UserPaths(config_dir=tmp_path / "c", state_dir=tmp_path / "s", cache_dir=tmp_path / "k")
    window = window_factory(service)
    assert install_preferences(
        window=window, source=service, env=PreferencesEnv(paths=paths, home=tmp_path)
    )
    present_and_settle(window)

    window.activate_action("win.preferences", None)
    wait_until(lambda: window.get_visible_dialog() is not None, description="first dialog")
    first = window.get_visible_dialog()
    assert isinstance(first, PreferencesDialog)
    window.activate_action("win.preferences", None)
    main_context_iterate()

    assert window.get_visible_dialog() is first
    first.force_close()
