import pytest

from tests.ui.conftest import (
    WindowFactory,
    main_context_iterate,
)
from tests.ui.window_outcome_helpers import (
    FORCE,
    button_labelled,
    confirmed,
    finish,
    flow_of,
    not_responding,
    open_details,
    outcome_rows,
    ready,
    shown,
)
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.model.errors import ProtectedTarget
from wimm.service.control_protocols import StepStatus

pytestmark = pytest.mark.ui


def test_a_process_that_ignores_sigterm_offers_force_kill_as_a_new_plan(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = not_responding(window, service)
    details = open_details(window)
    assert outcome_rows(details) == [(plan.steps[0].target_label, "Non risponde")]
    force = button_labelled(details.get_extra_child() or details, FORCE)
    assert force is not None
    executed_before = len(service.executed)

    force.emit("clicked")
    main_context_iterate()

    kill = ActionRequest(kind=ActionKind.PROCESS_KILL, target_id=TargetId("1"))
    assert service.planned[-1] == kill
    dialog = flow_of(window).dialog
    assert dialog is not None
    assert (dialog.get_heading() or "").startswith("Forzare la chiusura di")
    assert len(service.executed) == executed_before


def test_force_kill_is_not_offered_when_no_step_is_unresponsive(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    finish(service, plan, StepStatus.FAILED)
    main_context_iterate()

    details = open_details(window)

    assert button_labelled(details.get_extra_child() or details, FORCE) is None


def test_a_refused_force_kill_shows_the_planner_message(window_factory: WindowFactory) -> None:
    window, service = ready(window_factory)
    not_responding(window, service)
    details = open_details(window)
    service.plan_error = ProtectedTarget()
    force = button_labelled(details.get_extra_child() or details, FORCE)
    assert force is not None

    confirm_dialog = flow_of(window).dialog
    force.emit("clicked")
    main_context_iterate()

    assert flow_of(window).dialog is confirm_dialog  # no kill dialog opened
    shown(window, ProtectedTarget.user_message)
