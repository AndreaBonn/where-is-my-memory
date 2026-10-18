"""C4: after stopping containers the toast offers «Riaccendi», a plan like any other."""

from dataclasses import replace

import pytest
from gi.repository import Adw

from tests.core.planning_helpers import container, group, proc, snapshot
from tests.ui.conftest import FakeActionService, WindowFactory, main_context_iterate
from tests.ui.test_window_outcome import button_labelled, confirmed, flow_of, ready, shown
from wimm.core.planning_restart import StoppedContainer
from wimm.model.enums import ActionKind, Risk, TargetId
from wimm.model.snapshot import ActionOffer, Snapshot
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.window import MainWindow

pytestmark = pytest.mark.ui
RESTART = "Riaccendi"


def project_snapshot() -> Snapshot:
    project = replace(
        group(gid="p", name="whitebox", members=(proc(pid=1), container(cid="c1"))),
        primary_action=ActionOffer(kind=ActionKind.GROUP_STOP, risk=Risk.SAFE),
    )
    return snapshot(project)


def stop_project(window_factory: WindowFactory) -> tuple[MainWindow, FakeActionService, str]:
    window, service = ready(window_factory)
    service.publish(project_snapshot())
    main_context_iterate()
    plan = confirmed(window, service)
    outcomes = tuple(StepOutcome(order=s.order, status=StepStatus.DONE) for s in plan.steps)
    service.stopped[plan.plan_id] = (StoppedContainer(id="c1", label="name-c1"),)
    service.emit("action-finished", plan.plan_id, outcomes)
    main_context_iterate()
    return window, service, plan.plan_id


def test_a_finished_stop_of_containers_offers_to_start_them_again(
    window_factory: WindowFactory,
) -> None:
    window, service, plan_id = stop_project(window_factory)
    shown(window, "whitebox: arresto completato")
    button = button_labelled(window, RESTART)
    assert button is not None

    button.emit("clicked")
    dialog = flow_of(window).dialog
    assert dialog is not None
    assert dialog.get_heading() == "Riaccendere i contenitori appena fermati?"
    assert dialog.get_response_label(CONFIRM_RESPONSE) == RESTART
    assert "Quanto si libera" not in dialog.get_body()
    dialog.emit("response", CONFIRM_RESPONSE)

    assert service.planned[-1].kind is ActionKind.RESTART_STOPPED
    assert service.planned[-1].target_id == TargetId(plan_id)
    assert service.last_plan is not None
    assert service.executed[-1][0] == service.last_plan.plan_id


def test_a_finished_stop_of_processes_only_offers_no_restart(
    window_factory: WindowFactory,
) -> None:
    window, service = ready(window_factory)
    plan = confirmed(window, service)

    service.emit("action-finished", plan.plan_id, (StepOutcome(order=1, status=StepStatus.DONE),))
    main_context_iterate()

    shown(window, "whitebox: arresto completato")
    assert button_labelled(window, RESTART) is None


def test_restart_targets_the_plan_of_the_toast_even_after_a_later_action(
    window_factory: WindowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The later outcome replaces the toast on screen, so its button widget is being
    # dismissed: clicking that widget raced the close animation. The toast object keeps
    # its own handler, which is what must stay bound to the plan it announced.
    window, service = ready(window_factory)
    added: list[Adw.Toast] = []
    add_toast = window.toasts.add_toast

    def record(toast: Adw.Toast) -> None:
        added.append(toast)
        add_toast(toast)

    monkeypatch.setattr(window.toasts, "add_toast", record)
    service.publish(project_snapshot())
    main_context_iterate()
    plan = confirmed(window, service)
    outcomes = tuple(StepOutcome(order=s.order, status=StepStatus.DONE) for s in plan.steps)
    service.stopped[plan.plan_id] = (StoppedContainer(id="c1", label="name-c1"),)
    service.emit("action-finished", plan.plan_id, outcomes)
    main_context_iterate()
    (restart,) = [toast for toast in added if toast.get_button_label() == RESTART]

    later = StepOutcome(order=1, status=StepStatus.DONE)
    service.emit("action-finished", "a-later-plan", (later,))
    main_context_iterate()
    restart.emit("button-clicked")

    assert service.planned[-1].kind is ActionKind.RESTART_STOPPED
    assert service.planned[-1].target_id == TargetId(plan.plan_id)


def test_a_container_that_was_already_gone_is_not_offered_for_restart(
    window_factory: WindowFactory,
) -> None:
    # Only a container the plan really stopped (DONE) can be started again.
    window, service = ready(window_factory)
    service.publish(project_snapshot())
    main_context_iterate()
    plan = confirmed(window, service)
    container_step = next(s for s in plan.steps if s.kind is ActionKind.CONTAINER_STOP)
    outcomes = tuple(
        StepOutcome(
            order=s.order,
            status=StepStatus.ALREADY_GONE if s is container_step else StepStatus.DONE,
        )
        for s in plan.steps
    )

    service.emit("action-finished", plan.plan_id, outcomes)
    main_context_iterate()

    shown(window, "whitebox: arresto completato")
    assert button_labelled(window, RESTART) is None
