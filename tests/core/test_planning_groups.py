from dataclasses import replace

import pytest

from tests.core.planning_requests_helpers import _stop, _terminate
from wimm.core.planning import PlanningContext, plan_action
from wimm.core.risk_table import CONSEQUENCES, ConsequenceKey
from wimm.model.actions import (
    ActionRequest,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind, ActivityState, Category, Risk, TargetId
from wimm.model.errors import InvalidRequest, ProtectedTarget
from wimm.model.snapshot import Group

from .planning_helpers import container, context, group, proc, snapshot


def test_group_stop_terminates_processes_before_containers() -> None:
    members = (container(cid="db"), proc(pid=3), container(cid="cache"), proc(pid=4))
    project = group(gid="p", members=members)

    plan = plan_action(request=_stop("p"), snapshot=snapshot(project), context=context())

    assert [(s.order, s.kind) for s in plan.steps] == [
        (1, ActionKind.PROCESS_TERMINATE),
        (2, ActionKind.PROCESS_TERMINATE),
        (3, ActionKind.CONTAINER_STOP),
        (4, ActionKind.CONTAINER_STOP),
    ]
    assert [s.target_label for s in plan.steps][2:] == ["name-db", "name-cache"]
    assert plan.estimated_reclaim_ram == 100 + 100 + 300 + 300


def test_group_stop_skips_stopped_containers_and_empty_result_raises() -> None:
    project = group(gid="p", members=(container(cid="up"), container(cid="down", state="exited")))
    stopped = group(gid="s", members=(container(cid="x", state="exited"),))

    plan = plan_action(request=_stop("p"), snapshot=snapshot(project, stopped), context=context())

    assert [s.target_label for s in plan.steps] == ["name-up"]
    with pytest.raises(InvalidRequest):
        plan_action(request=_stop("s"), snapshot=snapshot(project, stopped), context=context())


def test_group_stop_on_protected_group_raises() -> None:
    system = group(
        gid="sys", category=Category.SYSTEM, members=(proc(pid=1, category=Category.SYSTEM),)
    )

    with pytest.raises(ProtectedTarget):
        plan_action(request=_stop("sys"), snapshot=snapshot(system), context=context())


def test_stop_all_idle_safe_plans_only_idle_safe_groups() -> None:
    idle_safe = group(gid="a", category=Category.DEV_SERVER, members=(proc(pid=1),))
    idle_caution = group(
        gid="b", category=Category.AI_CLI, members=(proc(pid=2, category=Category.AI_CLI),)
    )
    active_safe = group(
        gid="c", category=Category.DEV_SERVER, state=ActivityState.ACTIVE, members=(proc(pid=3),)
    )
    request = ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE)

    plan = plan_action(
        request=request, snapshot=snapshot(idle_safe, idle_caution, active_safe), context=context()
    )

    assert [(s.target_label, s.risk) for s in plan.steps] == [("node (pid 1)", Risk.SAFE)]
    assert plan.risk is Risk.SAFE
    assert plan.confirm_phrase is None


def test_stop_all_idle_safe_refuses_idle_group_mixing_safe_and_caution_members() -> None:
    mixed = group(
        gid="m",
        category=Category.DEV_SERVER,
        members=(proc(pid=1), proc(pid=2, category=Category.AI_CLI)),
    )
    request = ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE)

    with pytest.raises(InvalidRequest):
        plan_action(request=request, snapshot=snapshot(mixed), context=context())


def test_group_stop_with_two_danger_steps_confirms_the_first_name() -> None:
    vms = tuple(
        replace(proc(pid=pid, name=name), tool_label="virtual_machine")
        for pid, name in ((1, "qemu-first"), (2, "qemu-second"))
    )
    holder = group(gid="v", category=Category.DEV_SERVER, members=vms)

    plan = plan_action(request=_stop("v"), snapshot=snapshot(holder), context=context())

    assert [s.risk for s in plan.steps] == [Risk.DANGER, Risk.DANGER]
    assert plan.confirm_phrase == "qemu-first"


def test_stop_all_idle_safe_ignores_ignored_groups_and_raises_when_nothing_qualifies() -> None:
    ignored = group(gid="a", category=Category.DEV_SERVER, members=(proc(pid=1),), ignored=True)
    request = ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE)

    with pytest.raises(InvalidRequest):
        plan_action(request=request, snapshot=snapshot(ignored), context=context())


def test_stop_all_idle_safe_excludes_whole_group_by_group_id() -> None:
    first = group(gid="a", category=Category.DEV_SERVER, members=(proc(pid=1),))
    second = group(gid="b", category=Category.DEV_SERVER, members=(proc(pid=2),))
    request = ActionRequest(kind=ActionKind.STOP_ALL_IDLE_SAFE, excluded_ids=frozenset({"a"}))

    plan = plan_action(request=request, snapshot=snapshot(first, second), context=context())

    assert [s.target_label for s in plan.steps] == ["node (pid 2)"]


def test_group_stop_exclusion_removes_step_and_recomputes_estimate_and_risk() -> None:
    members = (
        proc(pid=1, reclaimable=100),
        proc(pid=2, category=Category.AI_CLI, reclaimable=50),
        container(cid="db", reclaimable=300),
    )
    project = group(gid="p", members=members)
    full = plan_action(request=_stop("p"), snapshot=snapshot(project), context=context())

    reduced = plan_action(
        request=_stop("p", excluded=frozenset({"2"})), snapshot=snapshot(project), context=context()
    )

    assert full.risk is Risk.CAUTION
    assert full.estimated_reclaim_ram == 450
    assert reduced.risk is Risk.SAFE
    assert reduced.estimated_reclaim_ram == 400
    assert [(s.order, s.target_label) for s in reduced.steps] == [
        (1, "node (pid 1)"),
        (2, "name-db"),
    ]
    assert len(reduced.consequences) < len(full.consequences)


def test_group_stop_excluding_every_step_raises_invalid_request() -> None:
    project = group(gid="p", members=(proc(pid=1),))

    with pytest.raises(InvalidRequest):
        plan_action(
            request=_stop("p", excluded=frozenset({"1"})),
            snapshot=snapshot(project),
            context=context(),
        )


def test_plan_action_is_deterministic_for_same_input() -> None:
    project = group(gid="p", members=(proc(pid=1), container(cid="db")))
    snap = snapshot(project)

    assert plan_action(request=_stop("p"), snapshot=snap, context=context()) == plan_action(
        request=_stop("p"), snapshot=snap, context=context()
    )


def _kill(pid: int) -> ActionRequest:
    return ActionRequest(kind=ActionKind.PROCESS_KILL, target_id=TargetId(str(pid)))


def _app(*, pid: int, name: str, has_documents: bool) -> Group:
    member = proc(pid=pid, name=name, category=Category.DESKTOP_APP, has_documents=has_documents)
    return group(gid=f"app{pid}", category=Category.DESKTOP_APP, members=(member,))


def test_plan_kill_of_app_with_documents_is_danger_with_name_phrase() -> None:
    snap = snapshot(_app(pid=11, name="gedit", has_documents=True))

    plan = plan_action(request=_kill(11), snapshot=snap, context=context())

    assert (plan.risk, plan.confirm_phrase) == (Risk.DANGER, "gedit")
    assert CONSEQUENCES[ConsequenceKey.KILL] in plan.consequences


def test_plan_kill_of_app_without_documents_is_caution_without_phrase() -> None:
    snap = snapshot(_app(pid=12, name="calc", has_documents=False))

    plan = plan_action(request=_kill(12), snapshot=snap, context=context())

    assert (plan.risk, plan.confirm_phrase) == (Risk.CAUTION, None)


def test_plan_terminate_foreground_process_states_foreground_consequence() -> None:
    fg = group(gid="fg", category=Category.DEV_SERVER, members=(proc(pid=1, is_foreground=True),))
    bg = group(gid="bg", category=Category.DEV_SERVER, members=(proc(pid=2),))
    snap = snapshot(fg, bg)

    foreground = plan_action(request=_terminate(1), snapshot=snap, context=context())
    background = plan_action(request=_terminate(2), snapshot=snap, context=context())

    assert foreground.consequences[0] == CONSEQUENCES[ConsequenceKey.FOREGROUND]
    assert foreground.risk is Risk.CAUTION
    assert CONSEQUENCES[ConsequenceKey.FOREGROUND] not in background.consequences
    assert background.risk is Risk.SAFE


def test_plan_fingerprint_carries_the_process_uid() -> None:
    dev = group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=8, uid=4242),))
    plan = plan_action(
        request=_terminate(8),
        snapshot=snapshot(dev),
        context=PlanningContext(owner_uid=4242),
    )

    fingerprint = plan.steps[0].fingerprint
    assert isinstance(fingerprint, ProcessFingerprint)
    assert fingerprint.uid == 4242


def test_plan_process_of_another_user_is_protected_and_skipped_in_group_stop() -> None:
    other = proc(pid=1, uid=0)
    mine = proc(pid=2)
    dev = group(gid="dev", category=Category.DEV_SERVER, members=(other, mine))

    with pytest.raises(ProtectedTarget):
        plan_action(request=_terminate(1), snapshot=snapshot(dev), context=context())
    plan = plan_action(request=_stop("dev"), snapshot=snapshot(dev), context=context())
    assert [s.target_label for s in plan.steps] == ["node (pid 2)"]


def test_plan_danger_with_empty_target_name_raises_instead_of_blank_phrase() -> None:
    snap = snapshot(_app(pid=13, name="", has_documents=True))

    with pytest.raises(InvalidRequest):
        plan_action(request=_kill(13), snapshot=snap, context=context())
