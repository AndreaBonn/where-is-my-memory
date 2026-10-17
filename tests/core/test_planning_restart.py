"""C4: «Riaccendi» plans a start of exactly the containers a stop plan stopped."""

import pytest

from wimm.core.planning import PlanningContext, plan_action
from wimm.core.planning_restart import StoppedContainer
from wimm.model.actions import ActionRequest, ContainerFingerprint, Plan
from wimm.model.enums import ActionKind, PlanId, Risk, TargetId
from wimm.model.errors import InvalidRequest

from .planning_helpers import NOW, OWNER_UID, snapshot

STOPPED = {
    "stop-plan": (
        StoppedContainer(id="c1", label="whitebox-api"),
        StoppedContainer(id="c2", label="whitebox-db"),
    )
}


def _restart(*, plan_id: str) -> Plan:
    request = ActionRequest(kind=ActionKind.RESTART_STOPPED, target_id=TargetId(plan_id))
    context = PlanningContext(
        owner_uid=OWNER_UID, now=lambda: NOW, new_plan_id=lambda: PlanId("p-2"), stopped=STOPPED
    )
    return plan_action(request=request, snapshot=snapshot(), context=context)


def test_restart_starts_every_container_the_stop_plan_stopped() -> None:
    plan = _restart(plan_id="stop-plan")

    assert [step.kind for step in plan.steps] == [ActionKind.CONTAINER_START] * 2
    assert [step.target_label for step in plan.steps] == ["whitebox-api", "whitebox-db"]
    assert plan.steps[0].fingerprint == ContainerFingerprint(id="c1", status="exited")
    assert plan.risk is Risk.SAFE
    assert plan.confirm_phrase is None
    assert (plan.estimated_reclaim_ram, plan.estimated_reclaim_disk) == (0, 0)
    assert plan.consequences == ("Il container riparte con la configurazione di prima.",)


def test_restart_of_a_plan_that_stopped_no_container_is_refused() -> None:
    with pytest.raises(InvalidRequest):
        _restart(plan_id="other-plan")
