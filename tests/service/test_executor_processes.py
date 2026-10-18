import signal

import pytest

from tests.service.executor_fakes import (
    CREATED_AT,
    OWNER_UID,
    WIMM_PID,
    FakeProcesses,
    live_process,
    make_plan,
    process_step,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveProcess, StepStatus
from wimm.service.errors import InvalidRequest, ProtectedTarget, TargetChanged
from wimm.service.executor import PlanExecutor

TARGET_PID = 4321


def build_executor(*, processes: FakeProcesses) -> PlanExecutor:
    return PlanExecutor(processes=processes, containers=None, owner_uid=OWNER_UID)


def test_execute_terminates_unprotected_process_of_the_user() -> None:
    processes = FakeProcesses(live={TARGET_PID: live_process(pid=TARGET_PID)})
    plan = make_plan(steps=[process_step(order=1, pid=TARGET_PID)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert [(o.order, o.status) for o in outcomes] == [(1, StepStatus.DONE)]
    assert processes.signals == [(TARGET_PID, signal.SIGTERM)]


def test_execute_protected_process_is_rejected_without_signals() -> None:
    processes = FakeProcesses(live={TARGET_PID: live_process(pid=TARGET_PID, protected=True)})
    plan = make_plan(steps=[process_step(order=1, pid=TARGET_PID)])

    with pytest.raises(ProtectedTarget):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []


def test_execute_process_of_another_uid_is_rejected_even_if_fingerprint_matches() -> None:
    processes = FakeProcesses(live={TARGET_PID: live_process(pid=TARGET_PID, uid=0)})
    plan = make_plan(steps=[process_step(order=1, pid=TARGET_PID, uid=0)])

    with pytest.raises(ProtectedTarget):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []


@pytest.mark.parametrize("victim", [WIMM_PID, 1])
def test_execute_wimm_and_its_ancestors_are_rejected(victim: int) -> None:
    processes = FakeProcesses(live={victim: live_process(pid=victim)})
    plan = make_plan(steps=[process_step(order=1, pid=victim)])

    with pytest.raises(ProtectedTarget):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []


def test_execute_reused_pid_raises_target_changed_without_signals() -> None:
    reused = LiveProcess(
        pid=TARGET_PID, create_time=CREATED_AT + 50, uid=OWNER_UID, cmdline=("x",), protected=False
    )
    processes = FakeProcesses(live={TARGET_PID: reused})
    plan = make_plan(steps=[process_step(order=1, pid=TARGET_PID)])

    with pytest.raises(TargetChanged):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []


def test_execute_same_start_time_but_other_cmdline_raises_target_changed() -> None:
    other = LiveProcess(
        pid=TARGET_PID, create_time=CREATED_AT, uid=OWNER_UID, cmdline=("other",), protected=False
    )
    processes = FakeProcesses(live={TARGET_PID: other})
    plan = make_plan(steps=[process_step(order=1, pid=TARGET_PID)])

    with pytest.raises(TargetChanged):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []


def test_execute_vanished_process_is_already_gone_and_plan_continues() -> None:
    second = TARGET_PID + 1
    processes = FakeProcesses(live={second: live_process(pid=second)})
    plan = make_plan(
        steps=[process_step(order=1, pid=TARGET_PID), process_step(order=2, pid=second)]
    )

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE, StepStatus.DONE]
    assert processes.signals == [(second, signal.SIGTERM)]


def test_execute_changed_target_rejects_whole_plan_before_touching_anything() -> None:
    second = TARGET_PID + 1
    processes = FakeProcesses(
        live={
            TARGET_PID: live_process(pid=TARGET_PID),
            second: live_process(pid=second, protected=True),
        }
    )
    plan = make_plan(
        steps=[process_step(order=1, pid=TARGET_PID), process_step(order=2, pid=second)]
    )

    with pytest.raises(ProtectedTarget):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []


def test_execute_unsupported_kind_is_invalid_request() -> None:
    step = process_step(order=1, pid=TARGET_PID, kind=ActionKind.PROCESS_KILL)
    processes = FakeProcesses(live={TARGET_PID: live_process(pid=TARGET_PID)})

    with pytest.raises(InvalidRequest):
        build_executor(processes=processes).execute(plan=make_plan(steps=[step]))

    assert processes.signals == []


def test_execute_live_uid_differing_from_the_fingerprint_uid_raises_target_changed() -> None:
    # The live process still belongs to the user; only the plan recorded another uid.
    processes = FakeProcesses(live={TARGET_PID: live_process(pid=TARGET_PID, uid=OWNER_UID)})
    plan = make_plan(steps=[process_step(order=1, pid=TARGET_PID, uid=OWNER_UID + 1)])

    with pytest.raises(TargetChanged):
        build_executor(processes=processes).execute(plan=plan)

    assert processes.signals == []
