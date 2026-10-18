"""Requests that name a target the snapshot does not hold are refused (spec 8.1)."""

import pytest

from wimm.core.planning import plan_action
from wimm.model.actions import ActionRequest, ContainerFingerprint
from wimm.model.enums import ActionKind, GroupId, TargetId
from wimm.model.errors import InvalidRequest

from .planning_helpers import container, context, group, proc, snapshot


def test_plan_unknown_container_target_is_invalid() -> None:
    project = group(gid="p", members=(container(cid="up"),))
    ghost = ActionRequest(kind=ActionKind.CONTAINER_STOP, target_id=TargetId("ghost"))
    known = ActionRequest(kind=ActionKind.CONTAINER_STOP, target_id=TargetId("up"))

    with pytest.raises(InvalidRequest, match="Unknown container ghost"):
        plan_action(request=ghost, snapshot=snapshot(project), context=context())
    plan = plan_action(request=known, snapshot=snapshot(project), context=context())
    assert plan.steps[0].fingerprint == ContainerFingerprint(id="up", status="running")


def test_plan_compose_project_without_containers_is_invalid() -> None:
    processes_only = group(gid="c", compose_project="whitebox", members=(proc(pid=3),))
    request = ActionRequest(kind=ActionKind.COMPOSE_DOWN, group_id=GroupId("c"))

    with pytest.raises(InvalidRequest, match="no containers"):
        plan_action(request=request, snapshot=snapshot(processes_only), context=context())
