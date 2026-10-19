"""T-6.29: the Seleziona mode of the Disco page (S16, S17): checks, button, clearing."""

import pytest

from tests.core.disk_helpers import MB
from tests.ui.disk_select_helpers import (
    DANGER_ENTRY,
    HF_ENTRY,
    MODEL_0,
    MODEL_1,
    NOW,
    UV_ENTRY,
    UV_SIZE,
    checks,
    free_selected,
    make_page,
    select_toggle,
    selection_report,
)
from wimm.ui.format import format_size

pytestmark = pytest.mark.ui
MODEL_SIZES = 9 * MB + 8 * MB


def test_checks_are_hidden_until_the_toggle_is_pressed(display: None) -> None:
    page = make_page()

    assert not any(c.get_visible() for c in checks(page).values())
    select_toggle(page).set_active(True)

    assert all(c.get_visible() for c in checks(page).values())


def test_only_selectable_rows_and_sub_rows_have_a_check(display: None) -> None:
    page = make_page()
    found = checks(page)

    assert {UV_ENTRY, HF_ENTRY, MODEL_0, MODEL_1} <= set(found)
    assert DANGER_ENTRY not in found


def test_ticking_two_rows_puts_count_and_size_in_the_button(display: None) -> None:
    page = make_page()
    select_toggle(page).set_active(True)
    assert not free_selected(page).get_sensitive()

    found = checks(page)
    found[UV_ENTRY].set_active(True)
    found[MODEL_0].set_active(True)

    expected = f"Libera i selezionati (2, {format_size(size=UV_SIZE + 9 * MB)})"
    assert free_selected(page).get_label() == expected
    assert free_selected(page).get_sensitive()


def test_ticking_the_whole_cache_unticks_its_model_and_back(display: None) -> None:
    page = make_page()
    select_toggle(page).set_active(True)
    found = checks(page)

    found[MODEL_0].set_active(True)
    found[HF_ENTRY].set_active(True)
    assert found[HF_ENTRY].get_active()
    assert not found[MODEL_0].get_active()

    found[MODEL_1].set_active(True)
    assert found[MODEL_1].get_active()
    assert not found[HF_ENTRY].get_active()


def test_the_button_hands_the_ticked_entries_to_the_callback(display: None) -> None:
    picked: list[frozenset[str]] = []
    page = make_page(picked=picked)
    select_toggle(page).set_active(True)
    found = checks(page)
    found[UV_ENTRY].set_active(True)
    found[MODEL_1].set_active(True)

    free_selected(page).emit("clicked")

    assert picked == [frozenset({UV_ENTRY, MODEL_1})]


def test_a_new_report_clears_the_checks_and_disables_the_button(display: None) -> None:
    page = make_page()
    select_toggle(page).set_active(True)
    checks(page)[UV_ENTRY].set_active(True)
    assert free_selected(page).get_sensitive()

    page.show_report(report=selection_report(), now=NOW, min_age_days=90)

    assert not any(c.get_active() for c in checks(page).values())
    assert not free_selected(page).get_sensitive()
    assert free_selected(page).get_label() == "Libera i selezionati"
    assert select_toggle(page).get_active()


def test_leaving_the_mode_clears_the_selection(display: None) -> None:
    page = make_page()
    toggle = select_toggle(page)
    toggle.set_active(True)
    checks(page)[UV_ENTRY].set_active(True)

    toggle.set_active(False)
    assert not any(c.get_visible() for c in checks(page).values())
    toggle.set_active(True)

    assert not checks(page)[UV_ENTRY].get_active()
    assert not free_selected(page).get_sensitive()


def test_busy_page_keeps_the_button_off(display: None) -> None:
    page = make_page()
    select_toggle(page).set_active(True)
    checks(page)[UV_ENTRY].set_active(True)

    page.set_busy(busy=True)
    assert not free_selected(page).get_sensitive()
    page.set_busy(busy=False)

    assert free_selected(page).get_sensitive()


@pytest.mark.usefixtures("english")
def test_texts_in_english(display: None) -> None:
    page = make_page()
    toggle = select_toggle(page)
    toggle.set_active(True)
    checks(page)[UV_ENTRY].set_active(True)

    assert toggle.get_label() == "Select"
    assert free_selected(page).get_label() == f"Free the selected (1, {format_size(size=UV_SIZE)})"
