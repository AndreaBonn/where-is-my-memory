import signal

from tests.service.executor_fakes import (
    OWNER_UID,
    WIMM_PID,
    FakeProcesses,
    live_process,
    make_plan,
    process_step,
)
from wimm.service.control_protocols import StepStatus
from wimm.service.executor import PlanExecutor

ROOT = 5000
CHILD = 5001
GRANDCHILD = 5002
TIMEOUT = 2.5


def build_executor(*, processes: FakeProcesses) -> PlanExecutor:
    return PlanExecutor(
        processes=processes, containers=None, owner_uid=OWNER_UID, terminate_timeout_s=TIMEOUT
    )


def tree_processes(*, stubborn: frozenset[int] = frozenset()) -> FakeProcesses:
    return FakeProcesses(
        live={pid: live_process(pid=pid) for pid in (ROOT, CHILD, GRANDCHILD)},
        tree={ROOT: (CHILD, GRANDCHILD)},
        stubborn=stubborn,
    )


def test_terminate_signals_descendants_before_the_root_and_never_sigkills() -> None:
    processes = tree_processes()
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert [pid for pid, _ in processes.signals] == [GRANDCHILD, CHILD, ROOT]
    assert {sig for _, sig in processes.signals} == {signal.SIGTERM}
    assert [o.status for o in outcomes] == [StepStatus.DONE]


def test_terminate_waits_on_the_whole_tree_with_the_configured_timeout() -> None:
    processes = tree_processes()
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    build_executor(processes=processes).execute(plan=plan)

    assert processes.waits == [((GRANDCHILD, CHILD, ROOT), TIMEOUT)]


def test_terminate_survivor_is_not_responding_and_still_gets_no_sigkill() -> None:
    processes = tree_processes(stubborn=frozenset({CHILD}))
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert outcomes[0].status is StepStatus.NOT_RESPONDING
    assert outcomes[0].message is not None and str(CHILD) in outcomes[0].message
    assert signal.SIGKILL not in {sig for _, sig in processes.signals}


def test_terminate_signal_failure_is_a_failed_step_and_others_still_run() -> None:
    other = 6000
    processes = tree_processes()
    processes.live[other] = live_process(pid=other)
    processes.failing = frozenset({ROOT})
    plan = make_plan(steps=[process_step(order=1, pid=ROOT), process_step(order=2, pid=other)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.FAILED, StepStatus.DONE]
    assert outcomes[0].message is not None
    assert (other, signal.SIGTERM) in processes.signals


def test_protected_descendant_fails_the_step_and_nothing_is_signalled() -> None:
    processes = tree_processes()
    processes.live[CHILD] = live_process(pid=CHILD, protected=True)
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert outcomes[0].status is StepStatus.FAILED
    assert processes.signals == []


def test_descendant_of_another_uid_fails_the_step_and_nothing_is_signalled() -> None:
    processes = tree_processes()
    processes.live[GRANDCHILD] = live_process(pid=GRANDCHILD, uid=0)
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert outcomes[0].status is StepStatus.FAILED
    assert processes.signals == []


def test_wimm_among_the_descendants_fails_the_step_and_nothing_is_signalled() -> None:
    processes = tree_processes()
    processes.live[WIMM_PID] = live_process(pid=WIMM_PID)
    processes.tree[ROOT] = (CHILD, WIMM_PID)
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert outcomes[0].status is StepStatus.FAILED
    assert processes.signals == []


def test_descendant_that_vanished_is_skipped_and_the_rest_is_terminated() -> None:
    processes = tree_processes()
    del processes.live[CHILD]
    plan = make_plan(steps=[process_step(order=1, pid=ROOT)])

    outcomes = build_executor(processes=processes).execute(plan=plan)

    assert outcomes[0].status is StepStatus.DONE
    assert [pid for pid, _ in processes.signals] == [GRANDCHILD, ROOT]


def test_failure_listing_children_is_a_failed_step_and_other_steps_report() -> None:
    first, broken, last = 7001, 7002, 7003
    processes = FakeProcesses(live={p: live_process(pid=p) for p in (first, broken, last)})
    processes.broken_trees = frozenset({broken})
    steps = [process_step(order=n, pid=p) for n, p in enumerate((first, broken, last), start=1)]

    outcomes = build_executor(processes=processes).execute(plan=make_plan(steps=steps))

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.FAILED, StepStatus.DONE]


def test_root_replaced_between_validation_and_its_step_fails_only_that_step() -> None:
    first, second = 7101, 7102
    processes = FakeProcesses(live={p: live_process(pid=p) for p in (first, second)})
    processes.on_wait = lambda: processes.live.update(
        {second: live_process(pid=second, protected=True)}
    )
    steps = [process_step(order=1, pid=first), process_step(order=2, pid=second)]

    outcomes = build_executor(processes=processes).execute(plan=make_plan(steps=steps))

    assert [o.status for o in outcomes] == [StepStatus.DONE, StepStatus.FAILED]
    assert (second, signal.SIGTERM) not in processes.signals
