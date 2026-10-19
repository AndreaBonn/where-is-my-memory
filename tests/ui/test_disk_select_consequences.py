"""F28: in a selection dialog each entry shows its own consequence, not one shared box (S16)."""

from dataclasses import replace

import pytest
from gi.repository import Adw, Gtk

from tests.core.disk_helpers import MB, docker_disk
from tests.ui.conftest import WindowFactory, descendants
from tests.ui.disk_actions_helpers import dialog_of, setup
from tests.ui.disk_select_helpers import (
    MODEL_0,
    MODEL_1,
    free_selected,
    select_toggle,
    selection_report,
)
from tests.ui.disk_select_helpers import checks as page_checks
from wimm.core.row_consequence import join_consequences
from wimm.model.actions import selected_entry_id
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind
from wimm.ui.dialogs.facts import WHAT_TITLE
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui

BUILD_ENTRY = selected_entry_id(kind=ActionKind.BUILDER_PRUNE, target_id=None)


def _report_with_build_cache() -> DiskReport:
    return replace(selection_report(), docker=docker_disk(build_cache_size=5 * MB))


def _open(window: MainWindow, *entries: str) -> list[Adw.SwitchRow]:
    select_toggle(window.disk).set_active(True)
    found = page_checks(window.disk)
    for entry in entries:
        found[entry].set_active(True)
    free_selected(window.disk).emit("clicked")
    extra = dialog_of(window).get_extra_child()
    assert extra is not None
    return [w for w in descendants(extra) if isinstance(w, Adw.SwitchRow)]


def _labels(window: MainWindow) -> list[str]:
    extra = dialog_of(window).get_extra_child()
    assert extra is not None
    return [w.get_label() for w in descendants(extra) if isinstance(w, Gtk.Label)]


def test_two_models_with_the_same_consequence_each_carry_it(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory, disk=selection_report())

    rows = _open(window, MODEL_0, MODEL_1)

    assert service.last_plan is not None
    expected = join_consequences(consequences=service.last_plan.steps[0].consequences)
    assert expected
    assert [row.get_subtitle() for row in rows] == [expected, expected]
    assert WHAT_TITLE not in _labels(window)


def test_a_model_and_the_build_cache_each_carry_their_own_text(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory, disk=_report_with_build_cache())

    rows = _open(window, MODEL_0, BUILD_ENTRY)

    assert service.last_plan is not None
    by_label = {
        step.target_label: join_consequences(consequences=step.consequences)
        for step in service.last_plan.steps
    }
    texts = [row.get_subtitle() or "" for row in rows]
    assert len(texts) == 2 and all(texts)
    assert texts[0] != texts[1]
    assert sorted(texts) == sorted(by_label.values())
