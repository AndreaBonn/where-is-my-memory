"""T-6.29: the one confirmation dialog of a selection (S16), and the changed-report case (S17)."""

import pytest
from gi.repository import Adw

from tests.core.disk_helpers import MB, cache, report
from tests.ui.conftest import WindowFactory, descendants, present_and_settle
from tests.ui.disk_actions_helpers import dialog_of, setup, toast_texts
from tests.ui.disk_select_helpers import (
    HF_ENTRY,
    MODEL_0,
    MODEL_1,
    UV_ENTRY,
    UV_SIZE,
    checks,
    free_selected,
    select_toggle,
    selection_report,
)
from wimm.model.actions import ActionRequest
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind, Risk
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.dialogs.session import CHANGED_NOTICE
from wimm.ui.format import format_size
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui


def _tick(window: MainWindow, *entries: str) -> None:
    select_toggle(window.disk).set_active(True)
    found = checks(window.disk)
    for entry in entries:
        found[entry].set_active(True)


def _group_titles(window: MainWindow) -> list[str]:
    extra = dialog_of(window).get_extra_child()
    assert extra is not None
    return [w.get_title() for w in descendants(extra) if isinstance(w, Adw.PreferencesGroup)]


def test_the_button_plans_the_selection_and_opens_one_dialog(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory, disk=selection_report())
    _tick(window, UV_ENTRY, MODEL_0)

    free_selected(window.disk).emit("clicked")

    assert service.planned == [
        ActionRequest(
            kind=ActionKind.DISK_FREE_SELECTED, selected_ids=frozenset({UV_ENTRY, MODEL_0})
        )
    ]
    dialog = dialog_of(window)
    assert dialog.get_heading() == "Liberare lo spazio delle voci scelte?"
    assert service.last_plan is not None
    assert service.last_plan.risk is Risk.CAUTION


def test_the_dialog_groups_the_entries_by_risk_class(window_factory: WindowFactory) -> None:
    window, _service = setup(window_factory, disk=selection_report())
    _tick(window, MODEL_0, UV_ENTRY)

    free_selected(window.disk).emit("clicked")

    assert _group_titles(window) == ["Sicuro", "Attenzione"]
    body = dialog_of(window).get_body()
    assert format_size(size=UV_SIZE + 9 * MB) in body
    assert body.startswith("In tutto liberi circa")


def test_unticking_an_entry_replans_without_it(window_factory: WindowFactory) -> None:
    window, service = setup(window_factory, disk=selection_report())
    _tick(window, MODEL_0, MODEL_1, UV_ENTRY)
    free_selected(window.disk).emit("clicked")
    dialog = dialog_of(window)
    extra = dialog.get_extra_child()
    assert extra is not None
    rows = [w for w in descendants(extra) if isinstance(w, Adw.SwitchRow)]
    assert len(rows) == 3
    caution = next(r for r in rows if "m1" in r.get_title())

    caution.set_active(False)

    assert service.planned[-1].selected_ids == frozenset({UV_ENTRY, MODEL_0})
    assert service.last_plan is not None
    assert len(service.last_plan.steps) == 2
    dialog.emit("response", CONFIRM_RESPONSE)
    assert service.executed == [(service.last_plan.plan_id, None)]


def test_a_safe_only_selection_keeps_the_safe_level(window_factory: WindowFactory) -> None:
    disk = report(caches=(cache(kind=CacheKind.UV, ino=1), cache(kind=CacheKind.PIP, ino=2)))
    window, service = setup(window_factory, disk=disk)
    _tick(window, UV_ENTRY, "cache_clean|pip")

    free_selected(window.disk).emit("clicked")

    assert service.last_plan is not None
    assert service.last_plan.risk is Risk.SAFE
    assert _group_titles(window) == ["Sicuro"]


def test_a_vanished_target_shows_the_changed_notice(window_factory: WindowFactory) -> None:
    window, service = setup(window_factory, disk=selection_report())
    _tick(window, UV_ENTRY, HF_ENTRY)
    service.set_report(report(caches=(cache(kind=CacheKind.UV, size=UV_SIZE, ino=12),)))

    free_selected(window.disk).emit("clicked")
    present_and_settle(window)

    assert window.action_flow is not None and window.action_flow.dialog is None
    assert CHANGED_NOTICE in toast_texts(window)


@pytest.mark.usefixtures("english")
def test_the_dialog_in_english(window_factory: WindowFactory) -> None:
    window, _service = setup(window_factory, disk=selection_report())
    _tick(window, MODEL_0, UV_ENTRY)

    free_selected(window.disk).emit("clicked")

    assert dialog_of(window).get_heading() == "Free the space of the chosen items?"
    assert _group_titles(window) == ["Safe", "Caution"]
