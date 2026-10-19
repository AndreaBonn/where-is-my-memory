from tests.core.planning_helpers import NOW, OWNER_UID, snapshot
from wimm.core.planning import PlanningContext, plan_action
from wimm.model.actions import (
    ActionRequest,
    Plan,
)
from wimm.model.disk import DiskReport
from wimm.model.enums import ActionKind, PlanId, TargetId


def _plan(*, kind: ActionKind, disk: DiskReport | None, target: str | None = None) -> Plan:
    request = ActionRequest(kind=kind, target_id=None if target is None else TargetId(target))
    context = PlanningContext(
        owner_uid=OWNER_UID,
        now=lambda: NOW,
        new_plan_id=lambda: PlanId("p-1"),
        disk_report=disk,
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)
