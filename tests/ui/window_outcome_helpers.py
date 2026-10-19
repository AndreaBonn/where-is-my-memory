from dataclasses import replace

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
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind, Risk
from wimm.model.snapshot import ActionOffer, Snapshot
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.action_flow import ActionFlow
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.widgets.group_row import PRIMARY_ACTION_NAME
from wimm.ui.window import MainWindow

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


def window_labels_of(dialog: Adw.AlertDialog) -> list[str]:
    extra = dialog.get_extra_child()
    assert extra is not None
    return [w.get_label() for w in descendants(extra) if isinstance(w, Gtk.Label)]


def not_responding(window: MainWindow, service: FakeActionService) -> Plan:
    plan = confirmed(window, service)
    outcome = StepOutcome(order=plan.steps[0].order, status=StepStatus.NOT_RESPONDING)
    service.emit("action-finished", plan.plan_id, (outcome,))
    main_context_iterate()
    return plan


def shown(window: Gtk.Window, text: str) -> None:
    """Wait for a toast to carry ``text``: the overlay shows one toast at a time."""
    wait_until(lambda: text in window_labels(window), description=f"toast {text!r}")


def finish(service: FakeActionService, plan: Plan, status: StepStatus) -> None:
    outcome = StepOutcome(order=plan.steps[0].order, status=status)
    service.emit("action-finished", plan.plan_id, (outcome,))


def two_process_project() -> Snapshot:
    project = replace(
        group(gid="p2", name="whitebox", members=(proc(pid=1), proc(pid=2))),
        primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE),
    )
    return snapshot(project)
