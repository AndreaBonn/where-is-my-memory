import pytest

from tests.core.planning_helpers import context, group, proc, snapshot
from wimm.core.planning import plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, GroupId
from wimm.service.errors import PlanExpired
from wimm.ui.dialogs.session import ConfirmSession, entries_for

GB = 1_000_000_000


@pytest.mark.usefixtures("english")
def test_a_refused_replan_shows_the_error_in_the_active_language() -> None:
    shown = snapshot(
        group(gid="p", name="whitebox", members=tuple(proc(pid=p, reclaimable=GB) for p in (1, 2)))
    )
    request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p"))
    first = plan_action(request=request, snapshot=shown, context=context())

    def replan(new: ActionRequest) -> Plan:
        raise PlanExpired

    session = ConfirmSession(
        plan=first,
        subject="whitebox",
        entries=entries_for(plan=first, snapshot=shown),
        replan=replan,
    )
    session.set_included(step_id="1", included=False)

    assert session.plan is None
    assert session.notice == "The plan has expired. Ask for a new preview"
