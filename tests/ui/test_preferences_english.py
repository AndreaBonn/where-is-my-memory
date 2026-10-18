"""The preferences dialog in English: group titles, rows, presets, messages and plurals."""

from pathlib import Path

import pytest
from gi.repository import Gtk

from tests.ui.conftest import FakeActionService
from tests.ui.test_preferences_dialog import home, paths, service, spin, tree
from tests.ui.test_preferences_simple import open_dialog, preset_button
from wimm.paths import UserPaths

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("english")]
__all__ = ["home", "paths", "service"]


def test_the_dialog_titles_and_alert_rows_are_in_english(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    assert dialog.get_title() == "Preferences"
    assert (
        spin(dialog, "notify_after_s").get_title()
        == "Alert me if you have not used it for (minutes)"
    )
    assert spin(dialog, "notify_min_bytes").get_title() == "Alert me only if it frees at least (MB)"
    assert dialog.advanced_row.get_title() == "Advanced settings"
    assert "closing and folders (15 items)" in (dialog.advanced_row.get_subtitle() or "")
    assert any(
        isinstance(w, Gtk.Button) and w.get_label() == "Restore the recommended values"
        for w in tree(dialog)
    )


def test_advanced_rows_and_groups_are_in_english(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    assert spin(dialog, "sample_interval_s").get_title() == "Check the memory every (seconds)"
    assert spin(dialog, "pressure_critical_pct").get_subtitle() == (
        "Must be lower than the previous threshold"
    )
    assert dialog.fields["foreground_tracking"].row.get_title() == (
        "Count the foreground program as in use"
    )
    assert dialog.fields["extra_protected_names"].row.get_title() == "Programs never to touch"


def test_the_presets_and_their_sentence_follow_the_language_with_plurals(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    assert preset_button(dialog, "Normal").get_active()
    preset_button(dialog, "Few").set_active(True)
    assert dialog.preset_text == (
        "Few: we alert you if something stays on unused for 4 hours and frees at least "
        "500 MB, up to 1 alert an hour (the others together in one)."
    )
    preset_button(dialog, "Many").set_active(True)
    assert "up to 6 alerts an hour" in dialog.preset_text


def test_a_hand_made_value_says_custom_in_english(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    spin(dialog, "notify_after_s").set_value(7)

    assert dialog.preset_text == (
        "Custom: the values chosen below and in the advanced settings apply."
    )


def test_apply_reports_in_english(
    display: None, service: FakeActionService, paths: UserPaths, home: Path
) -> None:
    dialog = open_dialog(service=service, paths=paths, home=home)

    dialog.apply()
    assert dialog.status_text == "No changes."
    spin(dialog, "notify_after_s").set_value(7)
    dialog.apply()
    assert dialog.status_text == "Preferences applied."
