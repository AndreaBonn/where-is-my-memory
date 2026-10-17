"""C4: after a stop the service can plan «Riaccendi» for the containers it stopped."""

import pytest

from tests.core.planning_helpers import container, group, proc, snapshot
from tests.service.service_helpers import spin_until
from tests.service.test_app_service_actions import RigFactory, rigs
from wimm.model.actions import ActionRequest
from wimm.model.enums import ActionKind, Category, GroupId, TargetId
from wimm.service.errors import InvalidRequest

__all__ = ["rigs"]


def test_containers_stopped_by_a_plan_can_be_started_again(rigs: RigFactory) -> None:
    base = snapshot(
        group(
            gid="p",
            category=Category.PROJECT,
            members=(proc(pid=8), container(cid="c1")),
        )
    )
    rig = rigs.build(base=base)
    stop = rig.service.plan(
        request=ActionRequest(kind=ActionKind.GROUP_STOP, group_id=GroupId("p"))
    )
    restart = ActionRequest(kind=ActionKind.RESTART_STOPPED, target_id=TargetId(stop.plan_id))
    with pytest.raises(InvalidRequest):
        rig.service.plan(request=restart)

    rig.service.execute(plan_id=stop.plan_id, typed_confirmation=None)
    spin_until(predicate=lambda: bool(rig.finished))
    plan = rig.service.plan(request=restart)

    assert [(s.kind, s.target_label) for s in plan.steps] == [
        (ActionKind.CONTAINER_START, "name-c1")
    ]
