from dataclasses import replace
from datetime import timedelta

import pytest

from tests.core.disk_helpers import VOLUME_CREATED_AT
from tests.core.planning_requests_helpers import ORPHANS, _terminate, _with_volumes
from wimm.core.planning import PlanningContext, plan_action
from wimm.core.risk_table import CONSEQUENCES, ConsequenceKey
from wimm.model.actions import (
    ActionRequest,
    ComposeFingerprint,
    ContainerFingerprint,
    ProcessFingerprint,
    VolumeFingerprint,
)
from wimm.model.enums import ActionKind, Category, GroupId, Risk, TargetId
from wimm.model.errors import InvalidRequest, ProtectedTarget
from wimm.model.raw import Mount

from .planning_helpers import NOW, OWNER_UID, container, context, group, proc, snapshot

SERVER_CMDLINE_SHA256 = "74a6f4f52c683695d2fe2f7e6acff4678117207ab5af3076c4dc0f279d2e3c27"


def test_plan_volume_remove_requires_volume_name_as_confirm_phrase() -> None:
    request = ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("pgdata"))

    plan = plan_action(request=request, snapshot=snapshot(), context=_with_volumes(context()))

    assert plan.confirm_phrase == "pgdata"
    assert plan.risk is Risk.DANGER
    assert plan.steps[0].fingerprint == VolumeFingerprint(
        name="pgdata", created_at=VOLUME_CREATED_AT
    )
    assert plan.steps[0].kind is ActionKind.VOLUME_REMOVE


def test_plan_protected_process_raises_protected_target() -> None:
    system = group(
        gid="sys",
        category=Category.SYSTEM,
        members=(proc(pid=7, name="gnome-shell", category=Category.SYSTEM),),
    )

    with pytest.raises(ProtectedTarget):
        plan_action(request=_terminate(7), snapshot=snapshot(system), context=context())


def test_plan_actionable_process_returns_fingerprinted_plan() -> None:
    dev = group(gid="dev", category=Category.DEV_SERVER, members=(proc(pid=8),))

    plan = plan_action(request=_terminate(8), snapshot=snapshot(dev), context=context())

    assert plan.risk is Risk.SAFE
    assert plan.confirm_phrase is None
    assert plan.steps[0].kind is ActionKind.PROCESS_TERMINATE
    assert plan.steps[0].fingerprint == ProcessFingerprint(
        pid=8, create_time=1008.5, uid=OWNER_UID, cmdline_hash=SERVER_CMDLINE_SHA256
    )
    assert plan.estimated_reclaim_ram == 100


def test_plan_process_without_offered_actions_raises_protected_target() -> None:
    shell = group(
        gid="t", category=Category.TERMINAL, members=(proc(pid=9, category=Category.SESSION),)
    )

    with pytest.raises(ProtectedTarget):
        plan_action(request=_terminate(9), snapshot=snapshot(shell), context=context())


def test_plan_actionable_process_without_offered_actions_raises_protected_target() -> None:
    bare = replace(proc(pid=9, category=Category.DEV_PROCESS), actions=())
    holder = group(gid="d", category=Category.DEV_PROCESS, members=(bare,))

    with pytest.raises(ProtectedTarget):
        plan_action(request=_terminate(9), snapshot=snapshot(holder), context=context())


def test_plan_unknown_process_raises_invalid_request() -> None:
    with pytest.raises(InvalidRequest):
        plan_action(request=_terminate(99), snapshot=snapshot(), context=context())


def test_plan_kill_of_database_process_is_danger_with_name_phrase() -> None:
    db = group(gid="db", category=Category.DEV_PROCESS, members=(proc(pid=5, name="postgres"),))
    web = group(gid="web", category=Category.DEV_SERVER, members=(proc(pid=6),))
    request = ActionRequest(kind=ActionKind.PROCESS_KILL, target_id=TargetId("5"))

    plan = plan_action(request=request, snapshot=snapshot(db, web), context=context())
    other = plan_action(
        request=ActionRequest(kind=ActionKind.PROCESS_KILL, target_id=TargetId("6")),
        snapshot=snapshot(db, web),
        context=context(),
    )

    assert (plan.risk, plan.confirm_phrase) == (Risk.DANGER, "postgres")
    assert (other.risk, other.confirm_phrase) == (Risk.CAUTION, None)


def test_plan_expires_120_seconds_after_creation_with_injected_id() -> None:
    plan = plan_action(
        request=ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("v")),
        snapshot=snapshot(),
        context=_with_volumes(context()),
    )

    assert plan.plan_id == "p-1"
    assert plan.created_at == NOW
    assert plan.expires_at == NOW + timedelta(seconds=120)


def test_plan_default_context_generates_distinct_urlsafe_ids() -> None:
    request = ActionRequest(kind=ActionKind.VOLUME_REMOVE, target_id=TargetId("v"))
    default = PlanningContext(owner_uid=OWNER_UID, disk_report=ORPHANS)

    first = plan_action(request=request, snapshot=snapshot(), context=default)
    second = plan_action(request=request, snapshot=snapshot(), context=default)

    assert first.plan_id != second.plan_id
    assert len(first.plan_id) == 22
    assert first.expires_at - first.created_at == timedelta(seconds=120)


def test_plan_container_stop_and_remove_follow_container_state() -> None:
    project = group(
        gid="p",
        members=(container(cid="up"), container(cid="down", state="exited")),
    )
    stop = ActionRequest(kind=ActionKind.CONTAINER_STOP, target_id=TargetId("up"))
    remove = ActionRequest(kind=ActionKind.CONTAINER_REMOVE, target_id=TargetId("down"))
    wrong = ActionRequest(kind=ActionKind.CONTAINER_STOP, target_id=TargetId("down"))

    stop_plan = plan_action(request=stop, snapshot=snapshot(project), context=context())
    remove_plan = plan_action(request=remove, snapshot=snapshot(project), context=context())

    assert stop_plan.steps[0].fingerprint == ContainerFingerprint(id="up", status="running")
    assert stop_plan.risk is Risk.SAFE
    assert CONSEQUENCES[ConsequenceKey.STOP_TIMEOUT] in stop_plan.consequences
    assert CONSEQUENCES[ConsequenceKey.STOP_TIMEOUT] not in remove_plan.consequences
    assert remove_plan.steps[0].fingerprint == ContainerFingerprint(id="down", status="exited")
    assert remove_plan.risk is Risk.CAUTION
    with pytest.raises(InvalidRequest):
        plan_action(request=wrong, snapshot=snapshot(project), context=context())


def test_plan_compose_down_volumes_is_danger_and_lists_volumes() -> None:
    mount = Mount(type="volume", source="/var/lib/docker/volumes/pgdata/_data", destination="/d")
    bind = Mount(type="bind", source="/home/u/code", destination="/app")
    project = group(
        gid="p",
        compose_project="name-p",
        members=(container(cid="a", mounts=(mount, bind)), container(cid="b")),
    )
    request = ActionRequest(kind=ActionKind.COMPOSE_DOWN_VOLUMES, group_id=GroupId("p"))

    plan = plan_action(request=request, snapshot=snapshot(project), context=context())

    assert plan.confirm_phrase == "name-p"
    assert plan.steps[0].fingerprint == ComposeFingerprint(
        project="name-p", container_ids=frozenset({"a", "b"})
    )
    assert any("pgdata" in line for line in plan.consequences)
    assert not any("/home/u/code" in line for line in plan.consequences)
    assert plan.estimated_reclaim_ram == 600


def test_plan_compose_uses_the_compose_project_not_the_displayed_group_name() -> None:
    fused = group(
        gid="f",
        name="cartella",
        compose_project="whitebox",
        members=(container(cid="a"), container(cid="b")),
    )
    request = ActionRequest(kind=ActionKind.COMPOSE_DOWN_VOLUMES, group_id=GroupId("f"))

    plan = plan_action(request=request, snapshot=snapshot(fused), context=context())

    assert plan.steps[0].fingerprint == ComposeFingerprint(
        project="whitebox", container_ids=frozenset({"a", "b"})
    )
    assert plan.confirm_phrase == "whitebox"


def test_plan_compose_on_a_group_without_compose_project_is_invalid() -> None:
    plain = group(gid="c", members=(container(cid="a"),))
    request = ActionRequest(kind=ActionKind.COMPOSE_DOWN, group_id=GroupId("c"))

    with pytest.raises(InvalidRequest, match="compose project"):
        plan_action(request=request, snapshot=snapshot(plain), context=context())


def test_plan_compose_down_on_protected_group_raises() -> None:
    system = group(
        gid="sys", category=Category.SYSTEM, members=(proc(pid=1, category=Category.SYSTEM),)
    )
    request = ActionRequest(kind=ActionKind.COMPOSE_DOWN, group_id=GroupId("sys"))

    with pytest.raises(ProtectedTarget):
        plan_action(request=request, snapshot=snapshot(system), context=context())


def test_plan_unsupported_kind_raises_invalid_request() -> None:
    project = group(gid="p", members=(container(cid="up"),))
    request = ActionRequest(kind=ActionKind.CONTAINER_START, target_id=TargetId("up"))

    with pytest.raises(InvalidRequest, match="cannot be planned"):
        plan_action(request=request, snapshot=snapshot(project), context=context())
