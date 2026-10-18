import os
import sys

import pytest

from tests.integration.live_targets import python_child, spawned
from tests.service.executor_fakes import (
    CMDLINE,
    OWNER_UID,
    FakeProcesses,
    live_process,
    make_plan,
    process_step,
)
from wimm.config import Config
from wimm.core.constants import TERMINATE_TIMEOUT_S
from wimm.service.control_protocols import StepStatus
from wimm.service.controls import PsutilProcessControl
from wimm.service.errors import ProtectedTarget
from wimm.service.executor import PlanExecutor

PID = 5000
NEW_TIMEOUT_S = 9


def build(*, processes: FakeProcesses) -> PlanExecutor:
    return PlanExecutor(processes=processes, containers=None, owner_uid=OWNER_UID)


def single_process() -> FakeProcesses:
    return FakeProcesses(live={PID: live_process(pid=PID)})


def test_apply_config_changes_the_timeout_of_the_next_terminate() -> None:
    processes = single_process()
    executor = build(processes=processes)
    plan = make_plan(steps=[process_step(order=1, pid=PID)])

    executor.execute(plan=plan)
    executor.apply_config(config=Config(terminate_timeout_s=NEW_TIMEOUT_S))
    executor.execute(plan=plan)

    assert [timeout for _, timeout in processes.waits] == [TERMINATE_TIMEOUT_S, NEW_TIMEOUT_S]


def test_apply_config_protects_a_name_added_by_the_user() -> None:
    processes = single_process()
    executor = build(processes=processes)
    plan = make_plan(steps=[process_step(order=1, pid=PID)])

    assert executor.execute(plan=plan)[0].status is StepStatus.DONE
    executor.apply_config(config=Config(extra_protected_names=(CMDLINE[0],)))
    with pytest.raises(ProtectedTarget):
        executor.execute(plan=plan)

    assert len(processes.signals) == 1


def test_apply_config_keeps_unrelated_names_actionable() -> None:
    executor = build(processes=single_process())
    executor.apply_config(config=Config(extra_protected_names=("other",)))
    plan = make_plan(steps=[process_step(order=1, pid=PID)])
    assert executor.execute(plan=plan)[0].status is StepStatus.DONE


def test_psutil_control_protects_a_name_added_after_construction() -> None:
    with spawned(args=python_child(script="import time; time.sleep(30)")) as child:
        # Remote sessions actionable: the suite may run over SSH, whose scope is protected.
        control = PsutilProcessControl(owner_uid=os.getuid(), remote_sessions_actionable=True)
        live = control.inspect(pid=child.pid)
        assert live is not None
        assert not live.protected, (
            "a child of this test must be actionable before the name is added"
        )
        control.set_extra_protected_names(names=(os.path.basename(sys.executable),))
        protected = control.inspect(pid=child.pid)
        assert protected is not None
        assert protected.protected


def test_apply_config_hands_the_remote_sessions_option_to_the_process_control() -> None:
    processes = single_process()
    executor = build(processes=processes)
    executor.apply_config(config=Config(remote_sessions_actionable=True))
    assert processes.remote_sessions_actionable is True
    executor.apply_config(config=Config())
    assert processes.remote_sessions_actionable is False
