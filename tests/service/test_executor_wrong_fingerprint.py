"""A step carrying the wrong kind of fingerprint is refused before its control is touched.

`PlanStep` already rejects the mismatch at construction, so the step is built right and the
fingerprint swapped afterwards: the executor must not trust the plan object it was handed.
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.service.compose_fakes import FakeCompose, compose_step
from tests.service.executor_fakes import (
    OWNER_UID,
    FakeDocker,
    FakeProcesses,
    container_step,
    image_step,
    live_process,
    make_plan,
    process_step,
    volume_step,
)
from tests.service.fs_fakes import build_rig, dir_plan, fingerprint_of, make_project
from wimm.model.actions import (
    DirFingerprint,
    PlanStep,
    ProcessFingerprint,
)
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import LiveContainer, StepStatus
from wimm.service.errors import InvalidRequest
from wimm.service.executor import PlanExecutor
from wimm.service.executor_docker import run_container_step

PID = 4100
IMAGE_ID = "sha256:" + "a" * 64
FOREIGN = DirFingerprint(realpath="/nowhere", st_ino=1, st_dev=1)
NOT_A_PROCESS = ProcessFingerprint(pid=1, create_time=1.0, uid=OWNER_UID, cmdline_hash="x")


class SpyProcesses(FakeProcesses):
    def __init__(self) -> None:
        super().__init__(live={PID: live_process(pid=PID)})
        self.touched: list[str] = []

    def inspect(self, *, pid: int):  # type: ignore[no-untyped-def]
        self.touched.append("inspect")
        return super().inspect(pid=pid)


class SpyDocker(FakeDocker):
    def __init__(self) -> None:
        super().__init__(live={"c1": LiveContainer(id="c1", status="running")})
        self.touched: list[str] = []

    def inspect(self, *, container_id: str):  # type: ignore[no-untyped-def]
        self.touched.append("inspect")
        return super().inspect(container_id=container_id)

    def inspect_image(self, *, image_id: str):  # type: ignore[no-untyped-def]
        self.touched.append("inspect_image")
        return super().inspect_image(image_id=image_id)

    def inspect_volume(self, *, name: str):  # type: ignore[no-untyped-def]
        self.touched.append("inspect_volume")
        return super().inspect_volume(name=name)


class SpyCompose(FakeCompose):
    def __init__(self) -> None:
        super().__init__()
        self.touched: list[str] = []

    def container_ids(self, *, project: str):  # type: ignore[no-untyped-def]
        self.touched.append("container_ids")
        return super().container_ids(project=project)


def _swapped(*, step: PlanStep, fingerprint: object) -> PlanStep:
    object.__setattr__(step, "fingerprint", fingerprint)
    return step


@dataclass(slots=True)
class Case:
    """An executor, the control it uses, and the step whose fingerprint can be swapped."""

    executor: PlanExecutor
    spy: SpyProcesses | SpyDocker | SpyCompose
    step: PlanStep
    wrong: object


def _process_case() -> Case:
    spy = SpyProcesses()
    executor = PlanExecutor(processes=spy, containers=None, owner_uid=OWNER_UID)
    return Case(executor=executor, spy=spy, step=process_step(order=1, pid=PID), wrong=FOREIGN)


def _container_case() -> Case:
    spy = SpyDocker()
    executor = PlanExecutor(processes=FakeProcesses(), containers=spy, owner_uid=OWNER_UID)
    step = container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_STOP)
    return Case(executor=executor, spy=spy, step=step, wrong=NOT_A_PROCESS)


def _compose_case() -> Case:
    spy = SpyCompose()
    executor = PlanExecutor(
        processes=FakeProcesses(), containers=None, owner_uid=OWNER_UID, compose=spy
    )
    return Case(
        executor=executor, spy=spy, step=compose_step(ids=frozenset({"a"})), wrong=NOT_A_PROCESS
    )


def _image_case() -> Case:
    spy = SpyDocker()
    executor = PlanExecutor(processes=FakeProcesses(), containers=spy, owner_uid=OWNER_UID)
    return Case(
        executor=executor, spy=spy, step=image_step(order=1, image_id=IMAGE_ID), wrong=NOT_A_PROCESS
    )


def _volume_case() -> Case:
    spy = SpyDocker()
    executor = PlanExecutor(processes=FakeProcesses(), containers=spy, owner_uid=OWNER_UID)
    return Case(
        executor=executor, spy=spy, step=volume_step(order=1, name="data"), wrong=NOT_A_PROCESS
    )


CASES: dict[str, Callable[[], Case]] = {
    "process": _process_case,
    "container": _container_case,
    "compose": _compose_case,
    "image": _image_case,
    "volume": _volume_case,
}


@pytest.mark.parametrize("name", CASES)
def test_step_with_the_wrong_fingerprint_type_rejects_the_plan_untouched(name: str) -> None:
    case = CASES[name]()
    _swapped(step=case.step, fingerprint=case.wrong)

    with pytest.raises(InvalidRequest, match="fingerprint"):
        case.executor.execute(plan=make_plan(steps=[case.step]))

    assert case.spy.touched == []


@pytest.mark.parametrize("name", CASES)
def test_step_with_the_right_fingerprint_does_reach_its_control(name: str) -> None:
    case = CASES[name]()

    # The step may fail later (nothing real behind the fakes); only the contact matters.
    with contextlib.suppress(Exception):
        case.executor.execute(plan=make_plan(steps=[case.step]))

    assert case.spy.touched != []


def test_devdir_step_with_the_wrong_fingerprint_type_rejects_the_plan(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home")
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=ActionKind.DEVDIR_DELETE, fingerprint=fingerprint_of(path=folder))
    _swapped(step=plan.steps[0], fingerprint=NOT_A_PROCESS)

    with pytest.raises(InvalidRequest, match="folder fingerprint"):
        rig.executor().execute(plan=plan)

    assert (folder / "top.txt").exists()


def test_container_step_run_with_the_wrong_fingerprint_fails_without_asking_docker() -> None:
    docker = SpyDocker()
    step = container_step(order=1, container_id="c1", kind=ActionKind.CONTAINER_STOP)
    _swapped(step=step, fingerprint=NOT_A_PROCESS)

    outcome = run_container_step(control=docker, step=step)

    assert outcome.status is StepStatus.FAILED
    assert outcome.message is not None and "container fingerprint" in outcome.message
    assert docker.touched == [] and docker.calls == []
    assert docker.live["c1"].status == "running"
