from tests.core.planning_helpers import context, group, proc, snapshot
from wimm.core.planning import plan_action
from wimm.model.actions import ActionRequest, Plan
from wimm.model.enums import ActionKind, GroupId
from wimm.model.snapshot import Snapshot
from wimm.ui.dialogs.session import CHANGED_NOTICE, ConfirmSession, entries_for

GB = 1_000_000_000


def project(*pids: int) -> Snapshot:
    return snapshot(
        group(gid="p", name="whitebox", members=tuple(proc(pid=p, reclaimable=GB) for p in pids))
    )


def session_on(*, shown: Snapshot, replanned: Snapshot) -> ConfirmSession:
    request = ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p"))
    first = plan_action(request=request, snapshot=shown, context=context())

    def replan(new: ActionRequest) -> Plan:
        return plan_action(request=new, snapshot=replanned, context=context())

    return ConfirmSession(
        plan=first,
        subject="whitebox",
        entries=entries_for(plan=first, snapshot=shown),
        replan=replan,
    )


def test_a_replan_with_a_target_never_shown_cannot_be_confirmed() -> None:
    # The sampler refreshed the snapshot while the dialog was open: pid 4 appeared.
    session = session_on(shown=project(1, 2, 3), replanned=project(1, 2, 3, 4))

    session.set_included(step_id="1", included=False)

    assert session.plan is None
    assert session.notice == CHANGED_NOTICE


def test_a_replan_within_the_shown_targets_keeps_the_plan() -> None:
    session = session_on(shown=project(1, 2, 3), replanned=project(1, 2, 3))

    session.set_included(step_id="1", included=False)

    assert session.plan is not None
    assert session.notice is None
    assert len(session.plan.steps) == 2


def test_a_replan_where_a_shown_target_is_gone_keeps_the_plan() -> None:
    session = session_on(shown=project(1, 2, 3), replanned=project(1, 2))

    session.set_included(step_id="1", included=False)

    assert session.plan is not None and len(session.plan.steps) == 1
