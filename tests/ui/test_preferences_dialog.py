from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from gi.repository import Adw, Gio, Gtk

from tests.ui.conftest import (
    FakeActionService,
    FakeSource,
    WindowFactory,
    descendants,
    make_group,
    present_and_settle,
    wait_until,
    with_groups,
)
from tests.ui.test_window_chrome import menu_item_states
from wimm.app import _install_preferences
from wimm.config import Config
from wimm.core.root_policy import RootRefusal
from wimm.model.enums import Category, GroupId
from wimm.model.snapshot import Snapshot
from wimm.paths import UserPaths
from wimm.service.errors import InvalidRequest
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


def spin(dialog: PreferencesDialog, key: str) -> Adw.SpinRow:
    row = dialog.fields[key].row
    assert isinstance(row, Adw.SpinRow)
    return row


def test_dialog_shows_the_values_in_use_in_readable_units(dialog: PreferencesDialog) -> None:
    assert spin(dialog, "sample_interval_s").get_value() == 45
    assert spin(dialog, "activity_window_s").get_value() == 30
    assert spin(dialog, "notify_min_bytes").get_value() == 200
    switch = dialog.fields["foreground_tracking"].row
    assert isinstance(switch, Adw.SwitchRow)
    assert switch.get_active() is True
    entries = list(descendants(dialog.fields["extra_protected_names"].row))
    assert [e.get_text() for e in entries if isinstance(e, Gtk.Entry)] == ["sshd"]


def test_number_rows_use_the_ranges_of_the_specification(dialog: PreferencesDialog) -> None:
    adjustment = spin(dialog, "sample_interval_s").get_adjustment()
    assert (adjustment.get_lower(), adjustment.get_upper()) == (10, 300)
    adjustment = spin(dialog, "pressure_critical_pct").get_adjustment()
    assert (adjustment.get_lower(), adjustment.get_upper()) == (1, 50)


def test_category_rows_follow_the_notified_categories(dialog: PreferencesDialog) -> None:
    checks = list(descendants(dialog.fields["notify_categories"].row))
    active = {w.get_name(): w.get_active() for w in checks if isinstance(w, Gtk.CheckButton)}
    assert active[Category.PROJECT.value] is True
    assert active[Category.AI_CLI.value] is False
    assert Category.SYSTEM.value not in active


def test_apply_sends_only_the_changed_field(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    spin(dialog, "sample_interval_s").set_value(60)

    dialog.apply()

    assert service.config_updates == [{"sample_interval_s": 60}]
    assert service.config().sample_interval_s == 60


def test_apply_without_changes_does_not_call_the_service(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    dialog.apply()
    spin(dialog, "sample_interval_s").set_value(60)
    dialog.apply()
    dialog.apply()

    assert service.config_updates == [{"sample_interval_s": 60}]


def test_apply_converts_minutes_back_to_seconds(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    spin(dialog, "activity_window_s").set_value(60)

    dialog.apply()

    assert service.config_updates == [{"activity_window_s": 3600}]


def test_field_error_is_shown_on_that_field_and_the_value_in_use_returns(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    spin(dialog, "pressure_critical_pct").set_value(20)

    dialog.apply()

    field = dialog.fields["pressure_critical_pct"]
    assert field.row.has_css_class("error")
    assert field.error == "Deve essere minore della soglia di avviso"
    assert spin(dialog, "pressure_critical_pct").get_value() == 10
    assert spin(dialog, "pressure_critical_pct").get_subtitle() == field.error
    others = [f for key, f in dialog.fields.items() if key != "pressure_critical_pct"]
    assert not [f for f in others if f.error is not None or f.row.has_css_class("error")]


def test_scripted_error_lands_on_the_named_field_only(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    service.scripted_errors = {"devdirs_max_depth": "Deve essere un numero intero fra 1 e 12"}
    spin(dialog, "devdirs_max_depth").set_value(9)
    spin(dialog, "sample_interval_s").set_value(100)

    dialog.apply()

    assert dialog.fields["devdirs_max_depth"].error == "Deve essere un numero intero fra 1 e 12"
    assert dialog.fields["sample_interval_s"].error is None
    assert spin(dialog, "devdirs_max_depth").get_value() == 6


def test_error_clears_when_the_next_apply_succeeds(
    dialog: PreferencesDialog, service: FakeActionService
) -> None:
    spin(dialog, "pressure_critical_pct").set_value(20)
    dialog.apply()
    spin(dialog, "pressure_critical_pct").set_value(12)

    dialog.apply()

    field = dialog.fields["pressure_critical_pct"]
    assert field.error is None
    assert not field.row.has_css_class("error")
    assert service.config().pressure_critical_pct == 12


def test_save_error_is_reported_and_the_dialog_stays_open(
    dialog: PreferencesDialog, service: FakeActionService, window_factory: WindowFactory
) -> None:
    window = window_factory(FakeSource(snapshot=service.snapshot()))
    present_and_settle(window)
    closed: list[bool] = []
    dialog.connect("closed", lambda *_a: closed.append(True))
    dialog.present(window)
    wait_until(dialog.get_mapped, description="dialog mapped")
    service.save_error = PermissionError("disco pieno")
    spin(dialog, "sample_interval_s").set_value(90)

    dialog.apply()

    assert "Impossibile salvare" in dialog.status_text
    assert closed == []
    assert dialog.get_mapped()
    dialog.force_close()


def test_menu_entry_is_enabled_only_when_the_source_can_update_the_config(
    window_factory: WindowFactory,
    service: FakeActionService,
    application: Gio.Application,
    paths: UserPaths,
    home: Path,
) -> None:
    env = PreferencesEnv(paths=paths, home=home)
    plain = window_factory(FakeSource(snapshot=service.snapshot()))
    full = window_factory(service)

    assert install_preferences(window=plain, source=FakeSource(snapshot=None), env=env) is False
    assert plain.window_actions.lookup_action("preferences") is None
    assert install_preferences(window=full, source=service, env=env) is True

    assert full.window_actions.lookup_action("preferences") is not None
    assert application.lookup_action("preferences") is None
    present_and_settle(full)
    assert menu_item_states(full)["Preferenze"] is True
    full.activate_action("win.preferences", None)
    wait_until(lambda: full.get_visible_dialog() is not None, description="dialog opened")
    opened = full.get_visible_dialog()
    assert isinstance(opened, PreferencesDialog)
    opened.force_close()


def tree(dialog: PreferencesDialog) -> Iterator[Gtk.Widget]:
    child = dialog.get_child()
    assert child is not None
    return descendants(child)


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
