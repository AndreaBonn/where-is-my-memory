"""R1-R5: the preferences as a non-expert meets them."""

from pathlib import Path

import pytest
from gi.repository import Adw, Gtk

from tests.ui.conftest import FakeActionService, descendants, main_context_iterate
from tests.ui.preferences_dialog_helpers import home, paths, service, spin, tree
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


def test_clicking_the_active_preset_again_keeps_it_chosen(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    normal = preset_button(dialog, "Normali")
    sentence = dialog.preset_text
    assert normal.get_active()

    normal.set_active(False)  # what a click on the already chosen preset does

    assert normal.get_active()
    assert dialog.preset_text == sentence != CUSTOM_SENTENCE
    assert spin(dialog, "notify_after_s").get_value() == 120
    # Positive control: a different preset does move the choice away from this one.
    preset_button(dialog, "Pochi").set_active(True)
    assert not normal.get_active()


def test_a_note_set_while_a_field_shows_an_error_waits_for_the_error_to_clear(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    item = dialog.fields["devdirs_roots"]
    base = item.base_subtitle

    item.set_note(lines=("nota uno",))
    assert item.row.get_subtitle() == f"{base}\nnota uno"

    item.show_error(message="non valido")
    item.set_note(lines=("nota due",))
    assert item.row.get_subtitle() == "non valido"

    item.clear_error()
    assert item.row.get_subtitle() == f"{base}\nnota due"


def test_an_error_on_a_key_the_dialog_does_not_show_still_reports_invalid_values(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    service.scripted_errors = {"no_such_key": "messaggio"}
    spin(dialog, "notify_after_s").set_value(90)

    dialog.apply()

    assert dialog.status_text == "Alcuni valori non sono validi: restano quelli in uso."
    assert all(status.has_css_class("error") for status in dialog._statuses)
    assert not any(item.error for item in dialog.fields.values())
    # Positive control: an error on a shown key marks that row too.
    service.scripted_errors = {"notify_after_s": "troppo basso"}
    spin(dialog, "notify_after_s").set_value(95)
    dialog.apply()
    assert dialog.fields["notify_after_s"].error == "troppo basso"


def test_folders_action_on_the_page_already_shown_puts_the_caret_at_the_end(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)
    entry = dialog.fields["devdirs_roots"].row.get_activatable_widget()
    dialog.advanced.emit("showing")  # the advanced page is on screen
    entry.set_text("/x/code, /x/work")
    entry.set_position(0)

    dialog.show_folders()
    main_context_iterate()

    assert entry.get_position() == len("/x/code, /x/work")
    assert not entry.get_selection_bounds()
