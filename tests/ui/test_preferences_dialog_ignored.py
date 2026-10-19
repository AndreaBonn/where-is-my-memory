from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from gi.repository import Adw, Gio, Gtk

from tests.ui.conftest import (
    FakeActionService,
    make_group,
    with_groups,
)
from tests.ui.preferences_dialog_helpers import spin, tree
from wimm.app import _install_preferences
from wimm.config import Config
from wimm.model.enums import GroupId
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.service.errors import InvalidRequest
from wimm.ui.dialogs.preferences import PreferencesDialog

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


def row_title(button: Gtk.Button) -> str:
    row = button.get_ancestor(Adw.ActionRow)
    assert isinstance(row, Adw.ActionRow)
    return row.get_title()


def ignored_buttons(dialog: PreferencesDialog) -> list[Gtk.Button]:
    return [
        w for w in tree(dialog) if isinstance(w, Gtk.Button) and w.get_label() == "Non ignorare più"
    ]


def ignored_service(snapshot: Snapshot, home: Path, *, count: int) -> FakeActionService:
    groups = tuple(
        replace(make_group(f"g{i}"), ignored=True, name=f"<b>g{i}</b>") for i in range(count)
    )
    return FakeActionService(
        snapshot=with_groups(snapshot, *groups, make_group("visible")),
        config=replace(Config(), devdirs_roots=(home / "dev",)),
    )


def test_ignored_groups_are_listed_and_unignore_calls_the_service(
    display: None, snapshot: Snapshot, paths: UserPaths, home: Path
) -> None:
    service = ignored_service(snapshot, home, count=2)
    dialog = PreferencesDialog(source=service, paths=paths, home=home)

    buttons = ignored_buttons(dialog)
    titles = [w.get_title() for w in tree(dialog) if isinstance(w, Adw.ActionRow)]
    assert len(buttons) == 2
    assert "<b>g0</b>" in titles and "visible" not in titles
    assert "Nessun programma senza avvisi" not in titles
    buttons[1].emit("clicked")

    assert service.ignored == [(GroupId("id-g1"), False)]
    assert len(ignored_buttons(dialog)) == 1


def test_no_ignored_groups_shows_the_empty_row(
    display: None, snapshot: Snapshot, paths: UserPaths, home: Path
) -> None:
    service = ignored_service(snapshot, home, count=0)
    dialog = PreferencesDialog(source=service, paths=paths, home=home)

    titles = [w.get_title() for w in tree(dialog) if isinstance(w, Adw.ActionRow)]
    assert "Nessun programma senza avvisi" in titles
    assert ignored_buttons(dialog) == []


def test_ignored_section_is_absent_without_set_ignored(
    display: None, snapshot: Snapshot, paths: UserPaths, home: Path
) -> None:
    class NoIgnore:
        def config(self) -> Config:
            return Config(devdirs_roots=(home / "dev",))

        def snapshot(self) -> Snapshot:
            return snapshot

    dialog = PreferencesDialog(source=NoIgnore(), paths=paths, home=home)

    titles = [w.get_title() for w in tree(dialog) if isinstance(w, Adw.PreferencesGroup)]
    assert "Programmi senza avvisi" not in titles
    assert "Avvisi" in titles


def test_install_preferences_wiring_in_app_needs_no_display() -> None:
    class Source:
        def config(self) -> Config:
            return Config()

        def update_config(self, **_kwargs: object) -> None: ...

    class FakeWindow:
        window_actions = Gio.SimpleActionGroup()

    application = SimpleNamespace(_service=Source())
    _install_preferences(application=application, window=FakeWindow())
    assert FakeWindow.window_actions.lookup_action("preferences") is not None
    other = FakeWindow()
    other.window_actions = Gio.SimpleActionGroup()
    _install_preferences(application=SimpleNamespace(_service=object()), window=other)
    assert other.window_actions.lookup_action("preferences") is None


def test_ignored_group_missing_from_the_snapshot_is_listed_and_can_be_restored(
    display: None, snapshot: Snapshot, paths: UserPaths, home: Path
) -> None:
    service = ignored_service(snapshot, home, count=1)
    service.extra_ignored = {GroupId("gone")}
    dialog = PreferencesDialog(source=service, paths=paths, home=home)

    rows = {
        w.get_title(): w.get_subtitle()
        for w in tree(dialog)
        if isinstance(w, Adw.ActionRow) and w.get_title() in ("<b>g0</b>", "gone")
    }
    assert rows == {"<b>g0</b>": "", "gone": "non attivo ora"}
    gone_button = next(b for b in ignored_buttons(dialog) if row_title(b) == "gone")
    gone_button.emit("clicked")
    assert service.ignored == [(GroupId("gone"), False)]


def test_ignored_groups_are_listed_before_the_first_snapshot(
    display: None, paths: UserPaths, home: Path
) -> None:
    class NoSnapshot:
        ignored: ClassVar[list[tuple[GroupId, bool]]] = []

        def config(self) -> Config:
            return Config(devdirs_roots=(home / "dev",))

        def snapshot(self) -> None:
            return None

        def ignored_group_ids(self) -> frozenset[GroupId]:
            return frozenset({GroupId("a")})

        def set_ignored(self, *, group_id: GroupId, ignored: bool) -> None:
            self.ignored.append((group_id, ignored))

    dialog = PreferencesDialog(source=NoSnapshot(), paths=paths, home=home)

    titles = [w.get_title() for w in tree(dialog) if isinstance(w, Adw.ActionRow)]
    assert "a" in titles
    assert "Nessun programma senza avvisi" not in titles


def test_wimm_error_on_save_is_reported_with_its_user_message(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    service.save_error = InvalidRequest("The service is stopped")
    spin(dialog, "sample_interval_s").set_value(90)

    dialog.apply()

    assert InvalidRequest.user_message in dialog.status_text
    assert "Impossibile salvare" in dialog.status_text


def test_apply_without_changes_clears_a_previous_invalid_status(
    dialog: PreferencesDialog,
) -> None:
    spin(dialog, "pressure_critical_pct").set_value(20)
    dialog.apply()
    assert "non sono validi" in dialog.status_text

    dialog.apply()

    assert dialog.status_text == "Nessuna modifica."
    assert not any(status.has_css_class("error") for status in dialog._statuses)
