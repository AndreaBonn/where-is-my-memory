import pytest
from gi.repository import Gtk

from tests.core.disk_helpers import (
    MB,
    report,
)
from tests.ui.conftest import WindowFactory, descendants, main_context_iterate
from tests.ui.disk_actions_helpers import (
    click_label,
    click_row,
    dialog_of,
    row_buttons,
    setup,
    toast_texts,
    type_phrase,
)
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, Risk
from wimm.model.errors import InvalidRequest
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE

pytestmark = pytest.mark.ui


def test_a_plan_error_shows_a_plain_message_and_no_dialog(window_factory: WindowFactory) -> None:
    window, service = setup(window_factory)
    service.set_report(report())  # the image vanished from the report after the page was built

    click_row(window, "myapp:dev")
    main_context_iterate()

    assert window.action_flow is not None
    assert window.action_flow.dialog is None
    assert InvalidRequest.user_message in toast_texts(window)


def test_a_plan_error_toast_is_not_shown_when_the_plan_succeeds(
    window_factory: WindowFactory,
) -> None:
    window, _ = setup(window_factory)

    click_row(window, "myapp:dev")
    main_context_iterate()

    assert dialog_of(window) is not None
    assert InvalidRequest.user_message not in toast_texts(window)


def test_the_outcome_toast_says_how_much_was_freed_without_details(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory)
    click_row(window, "Cache di build")
    dialog_of(window).emit("response", CONFIRM_RESPONSE)
    assert service.last_plan is not None

    done = StepOutcome(order=1, status=StepStatus.DONE, freed_bytes=100 * MB)
    service.emit("action-finished", service.last_plan.plan_id, (done,))
    main_context_iterate()

    assert "Cache di build: pulizia completata. Liberati 100 MB di disco" in toast_texts(window)
    buttons = [w.get_label() for w in descendants(window) if isinstance(w, Gtk.Button)]
    assert "Dettagli" not in buttons


def test_a_failed_target_is_reported_as_partial_with_details(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory)
    click_row(window, "pgdata")
    type_phrase(dialog_of(window), "pgdata")
    dialog_of(window).emit("response", CONFIRM_RESPONSE)
    assert service.last_plan is not None

    failed = StepOutcome(order=1, status=StepStatus.FAILED, message="in use")
    service.emit("action-finished", service.last_plan.plan_id, (failed,))
    main_context_iterate()

    texts = toast_texts(window)
    assert "pgdata: operazione non riuscita" in texts
    assert not any(t.startswith("Fatto") for t in texts)


def test_buttons_are_disabled_while_an_action_runs_and_back_after(
    window_factory: WindowFactory,
) -> None:
    window, service = setup(window_factory)
    (button,) = row_buttons(window, "myapp:dev")
    assert button.get_sensitive()

    click_row(window, "Cache di build")
    dialog_of(window).emit("response", CONFIRM_RESPONSE)
    assert not button.get_sensitive()
    assert service.last_plan is not None
    done = StepOutcome(order=1, status=StepStatus.DONE)
    service.emit("action-finished", service.last_plan.plan_id, (done,))

    assert button.get_sensitive()


def test_free_safe_plans_only_the_safe_items_and_asks_once(window_factory: WindowFactory) -> None:
    window, service = setup(window_factory)

    click_label(window, "Libera ")

    assert service.planned == [ActionRequest(kind=ActionKind.DISK_FREE_SAFE)]
    assert service.last_plan is not None
    assert {s.risk for s in service.last_plan.steps} == {Risk.SAFE}
    dialog = dialog_of(window)
    assert dialog.get_heading() == "Liberare lo spazio che si ricrea da solo?"
    dialog.emit("response", CONFIRM_RESPONSE)
    assert service.executed == [(service.last_plan.plan_id, None)]


def test_free_safe_with_nothing_left_says_so(window_factory: WindowFactory) -> None:
    from wimm.ui.action_flow import NOTHING_SAFE_ON_DISK_TEXT

    window, service = setup(window_factory)
    service.set_report(report())  # everything was cleaned since the page was built

    click_label(window, "Libera ")
    main_context_iterate()

    assert window.action_flow is not None
    assert window.action_flow.dialog is None
    assert NOTHING_SAFE_ON_DISK_TEXT in toast_texts(window)
