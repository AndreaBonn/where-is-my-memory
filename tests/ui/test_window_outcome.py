import pytest

from tests.ui.conftest import (
    FakeActionService,
    WindowFactory,
    main_context_iterate,
    present_and_settle,
)
from tests.ui.window_outcome_helpers import (
    DETAILS,
    GB,
    button_labelled,
    confirmed,
    finish,
    open_details,
    outcome_rows,
    primary_button,
    ready,
    shown,
    two_process_project,
    window_labels_of,
)
from wimm.model.errors import ProtectedTarget
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus

pytestmark = pytest.mark.ui


def test_finished_with_a_failure_offers_details_with_each_step_in_italian(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    label = plan.steps[0].target_label

    finish(service, plan, StepStatus.FAILED)
    main_context_iterate()

    shown(window, "whitebox: operazione non riuscita")
    assert outcome_rows(open_details(window)) == [(label, "Non riuscito")]


def test_finished_all_done_offers_no_details(window_factory: WindowFactory) -> None:
    # SPECIFICHE 10.3: "Dettagli" only when some target failed.
    window, service = ready(window_factory)
    plan = confirmed(window, service)

    finish(service, plan, StepStatus.DONE)
    main_context_iterate()

    shown(window, "whitebox: arresto completato")
    assert button_labelled(window, DETAILS) is None


def test_reclaim_measured_after_finished_shows_in_the_details(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    finish(service, plan, StepStatus.FAILED)
    main_context_iterate()
    before = open_details(window)
    assert "Liberati 1,1 GB di RAM" not in window_labels_of(before)

    service.emit(
        "reclaim-measured", plan.plan_id, ReclaimDelta(freed_ram=1_100_000_000, freed_disk=0)
    )
    main_context_iterate()

    assert "Liberati 1,1 GB di RAM" in window_labels_of(before)
    before.force_close()
    main_context_iterate()
    assert "Liberati 1,1 GB di RAM" in window_labels_of(open_details(window))


def test_reclaim_of_another_plan_or_nothing_freed_is_not_reported(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    finish(service, plan, StepStatus.FAILED)
    service.emit("reclaim-measured", "other-plan", ReclaimDelta(freed_ram=GB, freed_disk=0))
    service.emit("reclaim-measured", plan.plan_id, ReclaimDelta(freed_ram=-5, freed_disk=0))
    main_context_iterate()

    texts = window_labels_of(open_details(window))

    assert not [t for t in texts if t.startswith("Liberati")]


def test_the_row_button_is_busy_until_its_plan_finishes(window_factory: WindowFactory) -> None:
    window, service = ready(window_factory)
    button = primary_button(window)
    idle_label = button.get_label()
    plan = confirmed(window, service)

    assert not primary_button(window).get_sensitive()
    assert primary_button(window).get_label() == "In corso…"

    service.emit("action-finished", "someone-else", ())
    assert not primary_button(window).get_sensitive()

    finish(service, plan, StepStatus.DONE)
    assert primary_button(window).get_sensitive()
    assert primary_button(window).get_label() == idle_label


def test_the_row_button_is_enabled_again_when_the_plan_is_rejected(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    assert not primary_button(window).get_sensitive()

    service.emit("action-rejected", plan.plan_id, ProtectedTarget())

    assert primary_button(window).get_sensitive()
    shown(window, ProtectedTarget.user_message)


def test_a_partly_failed_plan_offers_details_even_if_another_step_succeeded(
    window_factory: WindowFactory,
) -> None:
    # SPECIFICHE 10.3: "Dettagli" appears when ANY target did not succeed.
    service = FakeActionService(snapshot=two_process_project())
    window = window_factory(service)
    present_and_settle(window)
    plan = confirmed(window, service)
    first, second = plan.steps[0].order, plan.steps[1].order
    outcomes = (
        StepOutcome(order=first, status=StepStatus.DONE),
        StepOutcome(order=second, status=StepStatus.FAILED),
    )

    service.emit("action-finished", plan.plan_id, outcomes)
    main_context_iterate()

    shown(window, "1 su 2 fermati, 1 non riuscito")
    assert button_labelled(window, DETAILS) is not None
