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
    shown,
)
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, TargetId
from wimm.model.errors import WimmError
from wimm.service.errors import PlanExpired, TargetChanged
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE

pytestmark = pytest.mark.ui


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
