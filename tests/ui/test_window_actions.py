from dataclasses import replace

import pytest
from gi.repository import Gtk

from tests.core.planning_helpers import container, group, proc, snapshot
from tests.ui.conftest import (
    FakeActionService,
    FakeSource,
    WindowFactory,
    descendants,
    main_context_iterate,
    present_and_settle,
)
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, Category, GroupId, Risk, TargetId
from wimm.model.errors import ProtectedTarget
from wimm.model.snapshot import ActionOffer, Member, Snapshot
from wimm.service.control_protocols import StepOutcome, StepStatus
from wimm.ui.dialogs.confirm import CONFIRM_RESPONSE
from wimm.ui.widgets.group_row import PRIMARY_ACTION_NAME
from wimm.ui.widgets.summary import SummaryPanel

pytestmark = pytest.mark.ui
GB = 1_000_000_000


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


def toast_texts(window: Gtk.Window) -> list[str]:
    return [w.get_label() for w in descendants(window) if isinstance(w, Gtk.Label)]


def test_clicking_the_row_button_plans_and_opens_the_dialog_then_confirm_executes(
    window_factory: WindowFactory,
) -> None:
    service = FakeActionService(snapshot=actionable_snapshot())
    window = window_factory(service)
    present_and_settle(window)
    button = primary_button(window)
    assert button.get_sensitive()

    button.emit("clicked")

    assert service.planned == [ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("srv"))]
    flow = window.action_flow
    assert flow is not None
    assert flow.dialog is not None
    assert flow.dialog.get_heading() == "Fermare whitebox?"
    assert service.executed == []
    flow.dialog.emit("response", CONFIRM_RESPONSE)
    assert len(service.executed) == 1
    assert service.executed[0][1] is None


def test_a_refused_plan_shows_a_toast_and_no_dialog(window_factory: WindowFactory) -> None:
    service = FakeActionService(snapshot=actionable_snapshot(), plan_error=ProtectedTarget())
    window = window_factory(service)
    present_and_settle(window)

    primary_button(window).emit("clicked")
    main_context_iterate()

    assert window.action_flow is not None
    assert window.action_flow.dialog is None
    assert ProtectedTarget.user_message in toast_texts(window)


def test_finished_action_tells_the_user_it_is_done(window_factory: WindowFactory) -> None:
    service = FakeActionService(snapshot=actionable_snapshot())
    window = window_factory(service)
    present_and_settle(window)

    done = (StepOutcome(order=0, status=StepStatus.DONE),)
    service.emit("action-finished", "p-1", done)
    main_context_iterate()

    assert "1 elemento: operazione completata" in toast_texts(window)


def test_without_an_action_service_the_button_stays_disabled(
    window_factory: WindowFactory,
) -> None:
    window = window_factory(FakeSource(snapshot=actionable_snapshot()))
    present_and_settle(window)

    assert not primary_button(window).get_sensitive()
    assert window.action_flow is None


def test_stop_all_button_is_enabled_with_a_handler_and_disabled_without(display: None) -> None:
    calls: list[str] = []

    wired = SummaryPanel(on_stop_all=lambda: calls.append("stop-all"))
    bare = SummaryPanel()

    (wired_button,) = [w for w in descendants(wired) if w.get_name() == "stop-all-idle"]
    (bare_button,) = [w for w in descendants(bare) if w.get_name() == "stop-all-idle"]
    assert isinstance(wired_button, Gtk.Button)
    assert wired_button.get_sensitive()
    wired_button.emit("clicked")
    assert calls == ["stop-all"]
    assert not bare_button.get_sensitive()


def test_a_second_confirm_on_the_same_dialog_executes_once(
    window_factory: WindowFactory,
) -> None:
    service = FakeActionService(snapshot=actionable_snapshot())
    window = window_factory(service)
    present_and_settle(window)
    primary_button(window).emit("clicked")
    flow = window.action_flow
    assert flow is not None and flow.dialog is not None

    flow.dialog.emit("response", CONFIRM_RESPONSE)
    flow.dialog.emit("response", CONFIRM_RESPONSE)

    assert len(service.executed) == 1


def test_stop_all_with_nothing_to_stop_says_so(window_factory: WindowFactory) -> None:
    from wimm.ui.action_flow import NOTHING_TO_STOP_TEXT

    service = FakeActionService(snapshot=snapshot())  # no idle safe group at all
    window = window_factory(service)
    present_and_settle(window)
    flow = window.action_flow
    assert flow is not None

    flow.start(request=ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE), subject=None)
    main_context_iterate()

    assert flow.dialog is None
    assert NOTHING_TO_STOP_TEXT in toast_texts(window)


def single_member_snapshot(*, member: Member, kind: ActionKind) -> Snapshot:
    row_group = replace(
        group(gid="solo-group", name="solo", members=(member,), category=Category.DEV_SERVER),
        primary_action=ActionOffer(kind=kind, risk=Risk.SAFE),
    )
    return snapshot(row_group)


@pytest.mark.parametrize(
    ("member", "kind", "expected_target"),
    [
        (proc(pid=4242), ActionKind.PROCESS_TERMINATE, "4242"),
        (container(cid="cont-9"), ActionKind.CONTAINER_STOP, "cont-9"),
    ],
)
def test_a_target_shaped_row_action_points_at_the_member_not_the_group(
    window_factory: WindowFactory, member: Member, kind: ActionKind, expected_target: str
) -> None:
    service = FakeActionService(snapshot=single_member_snapshot(member=member, kind=kind))
    window = window_factory(service)
    present_and_settle(window)

    primary_button(window).emit("clicked")

    assert service.planned == [ActionRequest(kind=kind, target_id=TargetId(expected_target))]


def test_a_target_shaped_row_action_points_at_the_member_that_offers_it(
    window_factory: WindowFactory,
) -> None:
    without_offers = replace(proc(pid=1), actions=())
    offering = proc(pid=2)
    row_group = replace(
        group(gid="two", name="two", members=(without_offers, offering)),
        primary_action=ActionOffer(kind=ActionKind.PROCESS_TERMINATE, risk=Risk.SAFE),
    )
    service = FakeActionService(snapshot=snapshot(row_group))
    window = window_factory(service)
    present_and_settle(window)

    primary_button(window).emit("clicked")

    assert service.planned == [
        ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId("2"))
    ]
