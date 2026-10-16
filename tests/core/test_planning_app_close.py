from dataclasses import replace

import pytest

from wimm.core.planning import plan_action
from wimm.core.risk_table import CONSEQUENCES, ConsequenceKey
from wimm.model.actions import ActionRequest, ProcessFingerprint
from wimm.model.enums import ActionKind, Category, GroupId, Risk
from wimm.model.errors import InvalidRequest, ProtectedTarget
from wimm.model.snapshot import Group, ProcessMember

from .planning_helpers import OWNER_UID, context, group, proc, snapshot

APP_ID = "g_app"


def _close(gid: str = APP_ID) -> ActionRequest:
    return ActionRequest(kind=ActionKind.APP_CLOSE, group_id=GroupId(gid))


def _member(*, pid: int, created: float, used: int = 100, uid: int = OWNER_UID) -> ProcessMember:
    base = proc(pid=pid, name="firefox", category=Category.BROWSER, reclaimable=used, uid=uid)
    return replace(base, create_time=created)


def _app(*members: ProcessMember, category: Category = Category.BROWSER) -> Group:
    return group(gid=APP_ID, category=category, members=members)


def test_app_close_plans_a_single_step_on_the_oldest_member() -> None:
    # Children are listed first and one is far heavier: neither may win over age.
    members = (
        _member(pid=30, created=2000.0, used=9000),
        _member(pid=10, created=1000.0, used=10),
        _member(pid=20, created=1500.0, used=500),
    )

    plan = plan_action(request=_close(), snapshot=snapshot(_app(*members)), context=context())

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.kind is ActionKind.APP_CLOSE
    assert isinstance(step.fingerprint, ProcessFingerprint)
    assert step.fingerprint.pid == 10
    assert step.fingerprint.create_time == 1000.0


def test_app_close_tie_on_age_goes_to_the_lowest_pid_whatever_the_memory() -> None:
    members = (
        _member(pid=12, created=1000.0, used=900),
        _member(pid=11, created=1000.0, used=10),
    )

    plan = plan_action(request=_close(), snapshot=snapshot(_app(*members)), context=context())

    fingerprint = plan.steps[0].fingerprint
    assert isinstance(fingerprint, ProcessFingerprint)
    assert fingerprint.pid == 11


def test_app_close_age_still_beats_a_lower_pid() -> None:
    members = (_member(pid=5, created=2000.0), _member(pid=90, created=1000.0))

    plan = plan_action(request=_close(), snapshot=snapshot(_app(*members)), context=context())

    fingerprint = plan.steps[0].fingerprint
    assert isinstance(fingerprint, ProcessFingerprint)
    assert fingerprint.pid == 90


def test_app_close_on_a_terminal_closes_the_terminal_server_with_its_consequence() -> None:
    # Section 5.3: TERMINAL "chiudi" is caution and closes every window and tab.
    terminal = _app(
        _member(pid=10, created=1000.0), _member(pid=11, created=1001.0), category=Category.TERMINAL
    )

    plan = plan_action(request=_close(), snapshot=snapshot(terminal), context=context())

    fingerprints = [step.fingerprint for step in plan.steps]
    assert all(isinstance(item, ProcessFingerprint) for item in fingerprints)
    assert [item.pid for item in fingerprints if isinstance(item, ProcessFingerprint)] == [10]
    assert plan.risk is Risk.CAUTION
    assert plan.consequences == (CONSEQUENCES[ConsequenceKey.TERMINAL],)


def test_app_close_is_refused_outside_apps_browsers_and_terminals() -> None:
    project = _app(_member(pid=10, created=1000.0), category=Category.DEV_SERVER)

    with pytest.raises(InvalidRequest):
        plan_action(request=_close(), snapshot=snapshot(project), context=context())


def test_app_close_is_caution_with_browser_consequence() -> None:
    plan = plan_action(
        request=_close(),
        snapshot=snapshot(_app(_member(pid=10, created=1000.0))),
        context=context(),
    )

    assert plan.risk is Risk.CAUTION
    assert plan.confirm_phrase is None
    assert plan.consequences == (CONSEQUENCES[ConsequenceKey.BROWSER],)
    assert plan.estimated_reclaim_ram == 100


def test_app_close_root_of_another_user_is_protected_with_positive_pair() -> None:
    mine = _app(_member(pid=10, created=1000.0))
    foreign = _app(_member(pid=10, created=1000.0, uid=OWNER_UID + 1))

    assert plan_action(request=_close(), snapshot=snapshot(mine), context=context()).steps
    with pytest.raises(ProtectedTarget):
        plan_action(request=_close(), snapshot=snapshot(foreign), context=context())


def test_app_close_on_protected_group_raises() -> None:
    shell = proc(pid=10, name="gnome-shell", category=Category.SYSTEM)
    system = _app(shell, category=Category.SYSTEM)

    with pytest.raises(ProtectedTarget):
        plan_action(request=_close(), snapshot=snapshot(system), context=context())


def test_app_close_on_non_app_or_unknown_group_raises_invalid_request() -> None:
    server = _app(_member(pid=10, created=1000.0), category=Category.DEV_SERVER)

    with pytest.raises(InvalidRequest):
        plan_action(request=_close(), snapshot=snapshot(server), context=context())
    with pytest.raises(InvalidRequest):
        plan_action(request=_close("g_none"), snapshot=snapshot(), context=context())


def test_app_close_without_process_members_raises_invalid_request() -> None:
    with pytest.raises(InvalidRequest):
        plan_action(request=_close(), snapshot=snapshot(_app()), context=context())
