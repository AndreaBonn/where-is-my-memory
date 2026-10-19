import pytest

from tests.ui.conftest import (
    WindowFactory,
    main_context_iterate,
)
from tests.ui.window_outcome_helpers import (
    confirmed,
    flow_of,
    primary_button,
    ready,
)
from wimm.service.errors import TargetChanged

pytestmark = pytest.mark.ui


def test_the_late_close_of_the_old_dialog_keeps_the_reference_to_the_replanned_one(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    old_dialog = flow_of(window).dialog
    service.emit("action-rejected", plan.plan_id, TargetChanged())
    main_context_iterate()
    new_dialog = flow_of(window).dialog
    assert new_dialog is not None and new_dialog is not old_dialog

    assert old_dialog is not None
    old_dialog.emit("closed")

    assert flow_of(window).dialog is new_dialog


def test_closing_the_current_dialog_clears_the_reference(window_factory: WindowFactory) -> None:
    window, _service = ready(window_factory)
    primary_button(window).emit("clicked")
    dialog = flow_of(window).dialog
    assert dialog is not None

    dialog.emit("closed")

    assert flow_of(window).dialog is None
