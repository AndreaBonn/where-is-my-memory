import signal

import pytest

from tests.service.executor_fakes import (
    CREATED_AT,
    OWNER_UID,
    FakeProcesses,
    live_process,
    make_plan,
    process_step,
)
from wimm.model.actions import Plan
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveProcess, StepStatus
from wimm.service.errors import ProtectedTarget, TargetChanged
from wimm.service.executor import PlanExecutor

ROOT = 7000
CHILDREN = (7001, 7002)
TIMEOUT = 1.5


def app_processes(*, stubborn: frozenset[int] = frozenset()) -> FakeProcesses:
    return FakeProcesses(
        live={pid: live_process(pid=pid) for pid in (ROOT, *CHILDREN)},
        tree={ROOT: CHILDREN},
        stubborn=stubborn,
    )


def executor(*, processes: FakeProcesses) -> PlanExecutor:
    return PlanExecutor(
        processes=processes, containers=None, owner_uid=OWNER_UID, terminate_timeout_s=TIMEOUT
    )


def close_plan(*, pid: int = ROOT) -> Plan:
    return make_plan(steps=[process_step(order=1, pid=pid, kind=ActionKind.APP_CLOSE)])


def test_app_close_sends_sigterm_to_the_root_only_and_waits_on_it() -> None:
    processes = app_processes()

    outcomes = executor(processes=processes).execute(plan=close_plan())

    assert processes.signals == [(ROOT, signal.SIGTERM)]
    assert processes.waits == [((ROOT,), TIMEOUT)]
    assert [o.status for o in outcomes] == [StepStatus.DONE]


def test_app_close_never_lists_children_unlike_terminate() -> None:
    processes = app_processes()
    processes.broken_trees = frozenset({ROOT})
    terminate = make_plan(steps=[process_step(order=1, pid=ROOT)])

    terminated = executor(processes=processes).execute(plan=terminate)
    closed = executor(processes=processes).execute(plan=close_plan())

    assert [o.status for o in terminated] == [StepStatus.FAILED]
    assert [o.status for o in closed] == [StepStatus.DONE]
    assert [pid for pid, _ in processes.signals] == [ROOT]


def test_app_close_root_that_ignores_sigterm_is_not_responding_without_sigkill() -> None:
    processes = app_processes(stubborn=frozenset({ROOT}))

    outcomes = executor(processes=processes).execute(plan=close_plan())

    assert outcomes[0].status is StepStatus.NOT_RESPONDING
    assert outcomes[0].message is not None and str(ROOT) in outcomes[0].message
    assert processes.signals == [(ROOT, signal.SIGTERM)]


def test_app_close_of_a_vanished_root_is_already_gone_and_signals_nobody() -> None:
    processes = FakeProcesses(live={}, tree={ROOT: CHILDREN})

    outcomes = executor(processes=processes).execute(plan=close_plan())

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]
    assert processes.signals == []


def test_app_close_revalidates_the_root_like_any_process_step() -> None:
    reused = app_processes()
    reused.live[ROOT] = LiveProcess(
        pid=ROOT,
        create_time=CREATED_AT + 5,
        uid=OWNER_UID,
        cmdline=live_process(pid=ROOT).cmdline,
        protected=False,
    )
    protected = app_processes()
    protected.live[ROOT] = live_process(pid=ROOT, protected=True)
    foreign = app_processes()
    foreign.live[ROOT] = live_process(pid=ROOT, uid=OWNER_UID + 1)

    with pytest.raises(TargetChanged):
        executor(processes=reused).execute(plan=close_plan())
    with pytest.raises(ProtectedTarget):
        executor(processes=protected).execute(plan=close_plan())
    with pytest.raises(ProtectedTarget):
        executor(processes=foreign).execute(plan=close_plan())
    for processes in (reused, protected, foreign):
        assert processes.signals == []


def test_unexpected_exception_in_a_step_is_a_failed_step_not_a_rejected_plan() -> None:
    other = 7100
    processes = app_processes()
    processes.live[other] = live_process(pid=other)
    processes.crashing = frozenset({ROOT})
    plan = make_plan(
        steps=[
            process_step(order=1, pid=ROOT, kind=ActionKind.APP_CLOSE),
            process_step(order=2, pid=other),
        ]
    )

    outcomes = executor(processes=processes).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.FAILED, StepStatus.DONE]
    assert outcomes[0].message is not None
    assert (other, signal.SIGTERM) in processes.signals


def test_app_close_whose_signal_fails_is_failed_with_the_reason_and_waits_for_nothing() -> None:
    processes = app_processes()
    processes.failing = frozenset({ROOT})

    outcomes = executor(processes=processes).execute(plan=close_plan())

    assert [o.status for o in outcomes] == [StepStatus.FAILED]
    assert outcomes[0].message == f"cannot signal {ROOT}"
    assert processes.waits == []
    assert processes.signals == []
