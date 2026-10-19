from dataclasses import replace
from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import (
    FakeActionService,
    WindowFactory,
    present_and_settle,
    wait_until,
)
from wimm.config import Config
from wimm.core.root_policy import RootRefusal
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog
from wimm.ui.window_preferences import PreferencesEnv, install_preferences

pytestmark = pytest.mark.ui


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "dev").mkdir()
    return tmp_path


@pytest.fixture
def paths(home: Path) -> UserPaths:
    return UserPaths(config_dir=home / "c", state_dir=home / "s", cache_dir=home / "k")


@pytest.fixture
def service(snapshot: Snapshot, home: Path) -> FakeActionService:
    config = replace(
        Config(),
        sample_interval_s=45,
        activity_window_s=1800,
        devdirs_roots=(home / "dev",),
        extra_protected_names=("sshd",),
    )
    return FakeActionService(snapshot=snapshot, config=config)


@pytest.fixture
def dialog(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> PreferencesDialog:
    return PreferencesDialog(source=service, paths=paths, home=home)


def test_missing_project_folder_is_flagged_in_the_folders_row(
    display: None,
    snapshot: Snapshot,
    paths: UserPaths,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Config, "refused_roots", property(lambda _self: ()))
    gone = home / "gone"
    config = replace(Config(), devdirs_roots=(home / "dev", gone))
    dialog = PreferencesDialog(
        source=FakeActionService(snapshot=snapshot, config=config), paths=paths, home=home
    )
    subtitle = dialog.fields["devdirs_roots"].row.get_subtitle()
    assert f"La cartella {gone} non esiste" in subtitle
    assert str(home / "dev") not in subtitle.split("\n", 1)[1]


def test_existing_project_folders_add_no_warning(
    dialog: PreferencesDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tmp_path sits under /tmp, which the real policy refuses; this test is about "missing".
    monkeypatch.setattr(Config, "refused_roots", property(lambda _self: ()))
    dialog._load_all()
    # Nothing to flag: the row keeps exactly its description, no note line appended.
    assert dialog.fields["devdirs_roots"].row.get_subtitle() == (
        "Percorsi di cartelle, anche fuori dalla tua cartella personale, separati da virgola"
    )


def test_folders_action_opens_the_advanced_page_on_the_folders_entry(
    window_factory: WindowFactory,
    service: FakeActionService,
    paths: UserPaths,
    home: Path,
) -> None:
    saved = (home / "code", home / "work")
    service.config_value = replace(service.config_value, devdirs_roots=saved)
    window = window_factory(service)
    install_preferences(window=window, source=service, env=PreferencesEnv(paths=paths, home=home))
    present_and_settle(window)

    window.activate_action("win.preferences-folders", None)

    wait_until(lambda: window.get_visible_dialog() is not None, description="dialog opened")
    opened = window.get_visible_dialog()
    assert isinstance(opened, PreferencesDialog)
    entry = opened.fields["devdirs_roots"].row.get_activatable_widget()
    # The caret lives in the GtkText inside the GtkEntry.
    wait_until(
        lambda: (focus := opened.get_focus()) is not None and focus.is_ancestor(entry),
        description="focus on the folders entry",
    )
    saved_text = entry.get_text()
    assert saved_text
    # Adwaita may move the focus again once its transition ends: wait for the caret itself.
    wait_until(
        lambda: not entry.get_selection_bounds() and entry.get_position() == len(saved_text),
        description="caret at the end of the saved folders",
    )
    assert not entry.get_selection_bounds()
    assert entry.get_position() == len(saved_text)
    # The guard against Adwaita's late select-all has its own test, independent of the window
    # manager: a real compositor may spend the one-shot guard before any grab simulated here.
    # The roots already typed must survive the first key press, and the row must be in view.
    typed = "/x/code, /x/work"
    entry.set_text(typed)
    opened.pop_subpage()
    opened.show_folders()
    wait_until(
        lambda: (focus := opened.get_focus()) is not None and focus.is_ancestor(entry),
        description="focus back on the folders entry",
    )
    wait_until(
        lambda: not entry.get_selection_bounds() and entry.get_position() == len(typed),
        description="caret at the end of the typed folders",
    )
    assert not entry.get_selection_bounds()
    assert entry.get_position() == len(typed)
    row = opened.fields["devdirs_roots"].row
    viewport = row.get_ancestor(Gtk.Viewport)

    def row_in_view() -> bool:
        found, bounds = row.compute_bounds(viewport)
        top, height = bounds.get_y(), viewport.get_height()
        return bool(found) and height > 0 and top >= 0 and top + bounds.get_height() <= height

    wait_until(row_in_view, description="folders row in view")
    # Positive control: the page is taller than the view, so being in view needed a scroll.
    assert viewport.get_vadjustment().get_upper() > viewport.get_height()
    assert viewport.get_vadjustment().get_value() > 0
    opened.force_close()


def test_refused_project_folder_shows_its_reason_in_the_folders_row(
    display: None,
    snapshot: Snapshot,
    paths: UserPaths,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = Path("/usr/share/fonts")
    monkeypatch.setattr(
        Config, "refused_roots", property(lambda _s: ((refused, RootRefusal.SYSTEM_PATH),))
    )
    config = replace(Config(), devdirs_roots=(home / "dev", refused))
    dialog = PreferencesDialog(
        source=FakeActionService(snapshot=snapshot, config=config), paths=paths, home=home
    )
    row = dialog.fields["devdirs_roots"].row
    assert (
        f"La cartella {refused} non viene usata. La cartella appartiene al sistema"
        in row.get_subtitle()
    )
    entry = row.get_activatable_widget()
    assert str(refused) in entry.get_text()
    assert str(home / "dev") not in row.get_subtitle().split("\n", 1)[1]


def test_remote_sessions_switch_is_off_and_explains_the_risk(dialog: PreferencesDialog) -> None:
    row = dialog.fields["remote_sessions_actionable"].row
    assert isinstance(row, Adw.SwitchRow)
    assert row.get_active() is False
    assert "interrompe il lavoro di chi è collegato" in (row.get_subtitle() or "")
    assert "SSH" in (row.get_title() or "")


def test_remote_sessions_switch_is_in_the_advanced_page(dialog: PreferencesDialog) -> None:
    row = dialog.fields["remote_sessions_actionable"].row
    assert row.get_ancestor(Adw.NavigationPage) is dialog.advanced


def test_remote_sessions_switch_applies_only_that_field(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    row = dialog.fields["remote_sessions_actionable"].row
    assert isinstance(row, Adw.SwitchRow)
    row.set_active(True)

    dialog.apply()

    assert service.config_updates == [{"remote_sessions_actionable": True}]
    assert service.config().remote_sessions_actionable is True
