"""R1-R5: the preferences as a non-expert meets them."""

from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import FakeActionService, descendants
from tests.ui.test_preferences_dialog import home, paths, service, spin, tree
from wimm.config import Config
from wimm.paths import UserPaths
from wimm.ui.dialogs.preferences import PreferencesDialog
from wimm.ui.dialogs.preferences_presets import CUSTOM_SENTENCE

pytestmark = pytest.mark.ui
__all__ = ["home", "paths", "service"]
ESSENTIAL = ("notify_after_s", "notify_min_bytes", "notify_categories")


def open_dialog(
    *, service: FakeActionService, paths: UserPaths, home: Path, session: str | None = "x11"
) -> PreferencesDialog:
    return PreferencesDialog(source=service, paths=paths, home=home, session_type=session)


def preset_button(dialog: PreferencesDialog, name: str) -> Gtk.ToggleButton:
    (button,) = [
        w for w in tree(dialog) if isinstance(w, Gtk.ToggleButton) and w.get_label() == name
    ]
    return button


def test_only_the_alerts_are_in_view_and_the_rest_is_one_click_away(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    in_view = {key for key, f in dialog.fields.items() if not f.row.is_ancestor(dialog.advanced)}
    assert in_view == set(ESSENTIAL)
    dialog.advanced_row.emit("activated")
    assert dialog.pop_subpage() is True


def test_a_preset_fills_the_three_alert_values_and_says_what_it_means(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    assert preset_button(dialog, "Normali").get_active()

    preset_button(dialog, "Pochi").set_active(True)

    assert spin(dialog, "notify_after_s").get_value() == 240
    assert spin(dialog, "notify_min_bytes").get_value() == 500
    assert spin(dialog, "max_notifications_per_hour").get_value() == 1
    assert dialog.preset_text.startswith("Pochi: ")
    dialog.apply()
    assert service.config_updates == [
        {"notify_after_s": 14400, "notify_min_bytes": 524288000, "max_notifications_per_hour": 1}
    ]


def test_a_value_set_by_hand_shows_custom_alerts(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    spin(dialog, "notify_after_s").set_value(90)

    assert not any(preset_button(dialog, n).get_active() for n in ("Pochi", "Normali", "Tanti"))
    assert dialog.preset_text == CUSTOM_SENTENCE


def test_recommended_values_are_restored_and_applied_keeping_names_and_folders(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    dialog.reset_button.emit("clicked")

    assert service.config().sample_interval_s == Config().sample_interval_s
    assert service.config().extra_protected_names == ("sshd",)
    assert spin(dialog, "sample_interval_s").get_value() == Config().sample_interval_s


@pytest.mark.parametrize(("session", "usable"), [("x11", True), ("wayland", False), (None, False)])
def test_foreground_option_is_off_where_it_cannot_work(
    display: None,
    service: FakeActionService,
    paths: UserPaths,
    home: Path,
    session: str | None,
    usable: bool,
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home, session=session)
    row = dialog.fields["foreground_tracking"].row
    assert isinstance(row, Adw.SwitchRow)

    assert row.get_sensitive() is usable
    assert ("Non disponibile" in (row.get_subtitle() or "")) is not usable


def test_reset_keeps_names_and_folders_even_when_edited_but_not_applied(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    entries = [
        w
        for w in descendants(dialog.fields["extra_protected_names"].row)
        if isinstance(w, Gtk.Entry)
    ]
    entries[0].set_text("sshd, firefox")

    dialog.reset_button.emit("clicked")

    assert service.config().extra_protected_names == ("sshd",)


def test_reset_leaves_the_foreground_option_alone_where_it_cannot_work(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    from dataclasses import replace

    service.config_value = replace(service.config_value, foreground_tracking=False)
    dialog = open_dialog(service=service, paths=paths, home=home, session="wayland")

    dialog.reset_button.emit("clicked")

    assert service.config().foreground_tracking is False


def test_an_invalid_advanced_value_is_pointed_to_from_the_main_page(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    spin(dialog, "pressure_critical_pct").set_value(20)

    dialog.apply()

    assert "Impostazioni avanzate" in dialog.status_text
