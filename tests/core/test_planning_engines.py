from dataclasses import replace

from wimm.core.planning import plan_action
from wimm.model.actions import ActionRequest, EngineIdentity, Plan
from wimm.model.enums import ActionKind, Category, TargetId

from .planning_helpers import context, group, proc, snapshot

DOCKER = EngineIdentity(path="/var/run/docker.sock", st_ino=10, st_dev=5)


def _terminate_plan(*, engines: tuple[EngineIdentity, ...] | None) -> Plan:
    ctx = context() if engines is None else replace(context(), engines=engines)
    snap = snapshot(group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=100),)))
    request = ActionRequest(kind=ActionKind.PROCESS_TERMINATE, target_id=TargetId("100"))
    return plan_action(request=request, snapshot=snap, context=ctx)


def test_plan_records_the_engines_of_the_context() -> None:
    assert _terminate_plan(engines=(DOCKER,)).engines == (DOCKER,)


def test_plan_has_no_engines_when_the_context_has_none() -> None:
    assert _terminate_plan(engines=None).engines == ()
