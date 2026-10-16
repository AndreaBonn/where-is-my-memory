import os
import subprocess
import sys

import psutil
import pytest

from tests.integration.live_targets import (
    PARENT_SCRIPT,
    STUBBORN_SCRIPT,
    process_step,
    python_child,
    single_step_plan,
    spawned,
    wait_ready,
)
from wimm.service.control_protocols import StepStatus
from wimm.service.controls import PsutilProcessControl
from wimm.service.executor import PlanExecutor

pytestmark = pytest.mark.integration
HTTP_SERVER = [sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1"]
SHORT_TIMEOUT_S = 0.5


def build_executor(*, control: PsutilProcessControl, timeout_s: float = 5) -> PlanExecutor:
    return PlanExecutor(
        processes=control,
        containers=None,
        owner_uid=os.getuid(),
        terminate_timeout_s=timeout_s,
    )


def require_actionable(*, control: PsutilProcessControl, child: subprocess.Popen[str]) -> None:
    live = control.inspect(pid=child.pid)
    assert live is not None
    if live.protected:
        pytest.skip("test child is categorized protected here (no systemd user session cgroup)")


def test_plan_terminates_an_http_server_created_by_the_test() -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=HTTP_SERVER) as child:
        require_actionable(control=control, child=child)
        plan = single_step_plan(step=process_step(pid=child.pid))

        outcomes = build_executor(control=control).execute(plan=plan)

        assert [o.status for o in outcomes] == [StepStatus.DONE]
        assert child.poll() is not None


def test_plan_terminates_the_whole_tree_of_a_parent_created_by_the_test() -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=python_child(script=PARENT_SCRIPT)) as child:
        wait_ready(child=child)
        require_actionable(control=control, child=child)
        grandchildren = psutil.Process(child.pid).children(recursive=True)
        assert grandchildren
        plan = single_step_plan(step=process_step(pid=child.pid))

        outcomes = build_executor(control=control).execute(plan=plan)

        assert [o.status for o in outcomes] == [StepStatus.DONE]
        assert not any(grandchild.is_running() for grandchild in grandchildren)


def test_process_ignoring_sigterm_is_not_responding_and_is_left_alive() -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=python_child(script=STUBBORN_SCRIPT)) as child:
        wait_ready(child=child)
        require_actionable(control=control, child=child)
        plan = single_step_plan(step=process_step(pid=child.pid))

        outcomes = build_executor(control=control, timeout_s=SHORT_TIMEOUT_S).execute(plan=plan)

        assert outcomes[0].status is StepStatus.NOT_RESPONDING
        assert child.poll() is None


def test_already_exited_child_is_already_gone() -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())
    with spawned(args=HTTP_SERVER) as child:
        require_actionable(control=control, child=child)
        step = process_step(pid=child.pid)
        child.kill()
        child.wait(timeout=5)

        outcomes = build_executor(control=control).execute(plan=single_step_plan(step=step))

        assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]


def test_real_control_reports_wimm_lineage_and_protects_system_processes() -> None:
    control = PsutilProcessControl(owner_uid=os.getuid())

    assert {os.getpid(), os.getppid()} <= control.self_lineage()
    init = control.inspect(pid=1)
    assert init is not None and init.protected
