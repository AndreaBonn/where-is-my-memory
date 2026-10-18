from dataclasses import replace

import pytest
from gi.repository import Adw, Gtk

from tests.core.planning_helpers import group, proc, snapshot
from tests.ui.conftest import (
    FakeActionService,
    WindowFactory,
    descendants,
    main_context_iterate,
    present_and_settle,
    wait_until,
)
from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, Risk, TargetId
from wimm.model.errors import ProtectedTarget, WimmError
from wimm.model.snapshot import ActionOffer, Snapshot
from wimm.service.actions import ReclaimDelta
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.service.errors import PlanExpired, TargetChanged
from wimm.ui.action_flow import ActionFlow
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.widgets.group_row import PRIMARY_ACTION_NAME
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui
GB = 1_000_000_000
DETAILS = "Dettagli"
FORCE = "Forza chiusura"


def actionable_snapshot() -> Snapshot:
    server = replace(
        group(gid="srv", name="whitebox", members=(proc(pid=1, reclaimable=GB),)),
        primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE),
    )
    return snapshot(server)


def primary_button(window: Gtk.Window) -> Gtk.Button:
    (button,) = [w for w in descendants(window) if w.get_name() == PRIMARY_ACTION_NAME]
    assert isinstance(button, Gtk.Button)
    return button


def window_labels(window: Gtk.Window) -> list[str]:
    return [w.get_label() for w in descendants(window) if isinstance(w, Gtk.Label)]


def button_labelled(root: Gtk.Widget, label: str) -> Gtk.Button | None:
    found = [w for w in descendants(root) if isinstance(w, Gtk.Button) and w.get_label() == label]
    return found[0] if found else None


def flow_of(window: MainWindow) -> ActionFlow:
    assert window.action_flow is not None
    return window.action_flow


def confirmed(window: MainWindow, service: FakeActionService) -> Plan:
    """Click the row button and confirm the dialog; return the plan that was executed."""
    primary_button(window).emit("clicked")
    dialog = flow_of(window).dialog
    assert dialog is not None
    dialog.emit("response", CONFIRM_RESPONSE)
    plan_id = service.executed[-1][0]
    plan = service.last_plan
    assert plan is not None and plan.plan_id == plan_id
    return plan


def outcome_rows(dialog: Adw.AlertDialog) -> list[tuple[str, str]]:
    extra = dialog.get_extra_child()
    assert extra is not None
    return [
        (w.get_title(), w.get_subtitle() or "")
        for w in descendants(extra)
        if isinstance(w, Adw.ActionRow)
    ]


def open_details(window: MainWindow) -> Adw.AlertDialog:
    button = button_labelled(window, DETAILS)
    assert button is not None
    button.emit("clicked")
    details = flow_of(window).details
    assert details is not None
    return details


def ready(window_factory: WindowFactory) -> tuple[MainWindow, FakeActionService]:
    service = FakeActionService(snapshot=actionable_snapshot())
    window = window_factory(service)
    present_and_settle(window)
    return window, service


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


def window_labels_of(dialog: Adw.AlertDialog) -> list[str]:
    extra = dialog.get_extra_child()
    assert extra is not None
    return [w.get_label() for w in descendants(extra) if isinstance(w, Gtk.Label)]


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


def test_a_changed_target_replans_once_and_reopens_the_dialog(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    first_dialog = flow_of(window).dialog

    service.emit("action-rejected", plan.plan_id, TargetChanged())
    main_context_iterate()

    request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=plan.request.group_id)
    assert service.planned == [request, request]
    new_dialog = flow_of(window).dialog
    assert new_dialog is not None and new_dialog is not first_dialog
    shown(window, "La situazione è cambiata, ricalcolo…")

    new_dialog.emit("response", CONFIRM_RESPONSE)
    service.emit("action-rejected", service.executed[-1][0], TargetChanged())
    main_context_iterate()

    assert len(service.planned) == 2
    assert flow_of(window).dialog is new_dialog  # no third dialog: the retry happens once
    shown(window, TargetChanged.user_message)
    assert primary_button(window).get_sensitive()


def not_responding(window: MainWindow, service: FakeActionService) -> Plan:
    plan = confirmed(window, service)
    outcome = StepOutcome(order=plan.steps[0].order, status=StepStatus.NOT_RESPONDING)
    service.emit("action-finished", plan.plan_id, (outcome,))
    main_context_iterate()
    return plan


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


def shown(window: Gtk.Window, text: str) -> None:
    """Wait for a toast to carry ``text``: the overlay shows one toast at a time."""
    wait_until(lambda: text in window_labels(window), description=f"toast {text!r}")


def finish(service: FakeActionService, plan: Plan, status: StepStatus) -> None:
    outcome = StepOutcome(order=plan.steps[0].order, status=status)
    service.emit("action-finished", plan.plan_id, (outcome,))


def test_an_unexpected_execute_failure_frees_the_buttons(
    window_factory: WindowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, service = ready(window_factory)

    def broken(*, plan_id: str, typed_confirmation: str | None) -> None:
        raise RuntimeError("bus gone")

    monkeypatch.setattr(service, "execute", broken)
    primary_button(window).emit("clicked")
    dialog = flow_of(window).dialog
    assert dialog is not None
    dialog.emit("response", CONFIRM_RESPONSE)
    main_context_iterate()

    assert primary_button(window).get_sensitive()  # not stuck "In corso…" forever
    shown(window, WimmError.user_message)


def test_a_changed_process_is_not_replanned_on_the_same_pid(
    window_factory: WindowFactory,
) -> None:
    # TargetChanged on a pid means the process was replaced: planning the pid again could
    # aim at another program, so the user gets the message instead of a new dialog.
    window, service = ready(window_factory)
    flow = flow_of(window)
    flow.start(
        request=ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId("1")),
        subject="node",
    )
    assert flow.dialog is not None
    flow.dialog.emit("response", CONFIRM_RESPONSE)

    service.emit("action-rejected", service.executed[-1][0], TargetChanged())
    main_context_iterate()

    assert len(service.planned) == 1
    shown(window, TargetChanged.user_message)


def test_an_expired_plan_replans_once_and_reopens_the_dialog(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)
    first_dialog = flow_of(window).dialog

    service.emit("action-rejected", plan.plan_id, PlanExpired())
    main_context_iterate()

    request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=plan.request.group_id)
    assert service.planned == [request, request]
    new_dialog = flow_of(window).dialog
    assert new_dialog is not None and new_dialog is not first_dialog
    shown(window, "La situazione è cambiata, ricalcolo…")


def two_process_project() -> Snapshot:
    project = replace(
        group(gid="p2", name="whitebox", members=(proc(pid=1), proc(pid=2))),
        primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE),
    )
    return snapshot(project)


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
