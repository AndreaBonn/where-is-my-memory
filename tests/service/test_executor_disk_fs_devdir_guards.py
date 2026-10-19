import logging
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.executor_disk_fs_helpers import DELETE, delete_devdir
from tests.service.fs_fakes import (
    MIN_AGE_DAYS,
    NOW,
    FsRig,
    age,
    build_rig,
    dir_plan,
    fingerprint_of,
    make_project,
)
from wimm.config import Config
from wimm.model.actions import DirFingerprint
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import (
    InvalidRequest,
    ProtectedTarget,
    TargetChanged,
)
from wimm.service.executor import PlanExecutor


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


def test_a_path_that_crosses_a_symlink_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    alias = rig.root / "alias"
    alias.symlink_to(folder.parent.parent)
    through = alias / folder.parent.name / folder.name

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=through))
    assert folder.exists()
    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE


def test_a_name_that_is_not_a_dependency_folder_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root, folder="node_module")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()

    exact = make_project(root=rig.root, name="other")
    assert delete_devdir(rig=rig, folder=exact) is StepStatus.DONE


def test_a_changed_inode_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    real = fingerprint_of(path=folder)
    forged = DirFingerprint(realpath=real.realpath, st_ino=real.st_ino + 1, st_dev=real.st_dev)

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=dir_plan(kind=DELETE, fingerprint=forged))
    assert (folder / "top.txt").exists()

    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, fingerprint=real))
    assert outcomes[0].status is StepStatus.DONE


def test_a_project_touched_since_the_plan_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=DELETE, path=folder)
    age(path=folder.parent / "package.json", mtime=NOW - 2 * 86400)

    with pytest.raises(TargetChanged, match="days ago"):
        rig.executor().execute(plan=plan)
    assert (folder / "top.txt").exists()

    age(path=folder.parent / "package.json", mtime=NOW - (MIN_AGE_DAYS + 1) * 86400)
    assert rig.executor().execute(plan=plan)[0].status is StepStatus.DONE


@pytest.mark.parametrize(("days", "allowed"), [(MIN_AGE_DAYS, True), (MIN_AGE_DAYS - 1, False)])
def test_a_project_exactly_at_the_minimum_age_is_old_enough(
    rig: FsRig, days: int, allowed: bool
) -> None:
    folder = make_project(root=rig.root)
    project = folder.parent
    for path in (project, project / "src", project / "package.json", project / "src" / "app.js"):
        age(path=path, mtime=NOW - days * 86400)
    plan = dir_plan(kind=DELETE, path=folder)

    if allowed:
        assert rig.executor().execute(plan=plan)[0].status is StepStatus.DONE
        assert not folder.exists()
    else:
        with pytest.raises(TargetChanged, match="days ago"):
            rig.executor().execute(plan=plan)
        assert (folder / "top.txt").exists()


def test_a_process_with_its_cwd_inside_the_project_blocks_the_deletion(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    rig.cwds.paths = [folder.parent / "src"]

    with pytest.raises(ProtectedTarget, match="working directory"):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()

    rig.cwds.paths = [rig.root / "another-project", rig.home]
    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE


def test_a_mounted_subfolder_is_skipped_and_its_content_survives(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    mount = folder / "pkg" / "mnt"
    mount.mkdir()
    (mount / "data.txt").write_text("mounted", encoding="utf-8")
    rig.control = replace(rig.control, mounts=lambda: frozenset({str(mount)}))

    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))

    assert outcomes[0].status is StepStatus.FAILED
    assert "1 entries left" in (outcomes[0].message or "")
    assert (mount / "data.txt").read_text(encoding="utf-8") == "mounted"
    assert not (folder / "top.txt").exists()
    assert not (folder / "pkg" / "index.js").exists()


def test_a_dependency_folder_that_is_itself_a_mount_is_refused_and_survives(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    rig.control = replace(rig.control, mounts=lambda: frozenset({str(folder)}))

    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))

    assert outcomes[0].status is StepStatus.FAILED
    assert (folder / "top.txt").exists() and (folder / "pkg" / "index.js").exists()

    rig.control = replace(rig.control, mounts=lambda: frozenset())
    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE


def test_a_project_that_cannot_be_read_for_its_age_is_not_deleted(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    source = folder.parent / "src"
    source.chmod(0o000)
    try:
        with pytest.raises(TargetChanged, match="could not be read"):
            rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
        assert (folder / "top.txt").exists()
    finally:
        source.chmod(0o700)

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE


def test_an_entry_that_cannot_be_removed_fails_the_step_with_a_count(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    locked = folder / "pkg" / "lib"
    locked.chmod(0o500)
    try:
        outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    finally:
        locked.chmod(0o700)

    assert outcomes[0].status is StepStatus.FAILED
    assert "1 entries left" in (outcomes[0].message or "")
    assert (locked / "util.js").exists()
    assert not (folder / "top.txt").exists()


def test_a_folder_that_vanished_is_already_gone(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=DELETE, path=folder)
    assert rig.executor().execute(plan=plan)[0].status is StepStatus.DONE

    assert rig.executor().execute(plan=plan)[0].status is StepStatus.ALREADY_GONE


def test_a_disk_action_is_rejected_when_the_executor_has_no_folder_control(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home")
    folder = make_project(root=rig.root)
    bare = PlanExecutor(processes=rig.executor().processes, containers=None, owner_uid=1000)

    with pytest.raises(InvalidRequest):
        bare.execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()


def test_apply_config_adopts_the_roots_and_the_minimum_age(rig: FsRig, tmp_path: Path) -> None:
    folder = make_project(root=rig.root)
    other_root = tmp_path / "home" / "other"
    other_root.mkdir()
    executor = rig.executor()
    executor.apply_config(
        config=Config(devdirs_roots=(other_root,), devdirs_min_age_days=MIN_AGE_DAYS)
    )

    with pytest.raises(ProtectedTarget):
        executor.execute(plan=dir_plan(kind=DELETE, path=folder))

    executor.apply_config(
        config=Config(devdirs_roots=(rig.root,), devdirs_min_age_days=MIN_AGE_DAYS)
    )
    assert executor.execute(plan=dir_plan(kind=DELETE, path=folder))[0].status is StepStatus.DONE


def test_the_disk_outcome_is_logged_with_its_bytes(
    rig: FsRig, caplog: pytest.LogCaptureFixture
) -> None:
    folder = make_project(root=rig.root)
    with caplog.at_level(logging.INFO, logger="wimm.service.executor_disk_docker"):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("disk action=")]
    assert len(lines) == 1
    assert "action=devdir_delete" in lines[0] and "outcome=done" in lines[0]
    assert "freed_bytes=unknown" not in lines[0]
