from dataclasses import replace
from pathlib import Path

import pytest
from gi.repository import Adw, Gio, Gtk

from tests.ui.conftest import (
    FakeActionService,
    FakeSource,
    WindowFactory,
    descendants,
    present_and_settle,
    wait_until,
)
from tests.ui.preferences_dialog_helpers import spin
from tests.ui.test_window_chrome import menu_item_states
from wimm.config import Config
from wimm.model.enums import Category
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
