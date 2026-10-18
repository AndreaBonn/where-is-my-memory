"""A folder or cache deleted between plan and run ends already_gone, never a raw exception."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.fs_fakes import FsRig, build_rig, dir_plan, make_cache, make_project
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus

DELETE = ActionKind.DEVDIR_DELETE
CLEAN = ActionKind.CACHE_CLEAN


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


def test_a_devdir_deleted_after_planning_is_already_gone(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=DELETE, path=folder)
    shutil.rmtree(folder)

    assert rig.executor().execute(plan=plan)[0].status is StepStatus.ALREADY_GONE


def test_a_devdir_whose_project_is_deleted_after_planning_is_already_gone(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=DELETE, path=folder)
    shutil.rmtree(folder.parent)

    assert rig.executor().execute(plan=plan)[0].status is StepStatus.ALREADY_GONE


def test_a_cache_deleted_after_planning_is_already_gone(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    plan = dir_plan(kind=CLEAN, path=folder)
    shutil.rmtree(folder)

    outcomes = rig.executor().execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE]
    assert rig.runner.calls == []


def test_a_vanished_folder_does_not_stop_the_other_steps(rig: FsRig) -> None:
    gone = make_project(root=rig.root, name="gone")
    kept = make_project(root=rig.root, name="kept")
    steps = [
        dir_plan(kind=DELETE, path=gone).steps[0],
        replace(dir_plan(kind=DELETE, path=kept).steps[0], order=2),
    ]
    plan = replace(dir_plan(kind=DELETE, path=kept), steps=tuple(steps))
    shutil.rmtree(gone)

    outcomes = rig.executor().execute(plan=plan)

    assert [o.status for o in outcomes] == [StepStatus.ALREADY_GONE, StepStatus.DONE]
    assert not kept.exists()
