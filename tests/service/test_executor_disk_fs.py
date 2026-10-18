import logging
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.fs_fakes import (
    MIN_AGE_DAYS,
    NOW,
    OLD,
    FsRig,
    age,
    build_rig,
    dir_plan,
    fingerprint_of,
    make_cache,
    make_project,
    make_trash,
)
from wimm.config import Config
from wimm.core.cache_catalog import CACHE_ENV_VARS
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S
from wimm.model.actions import DirFingerprint
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import ControlFailed, InvalidRequest, ProtectedTarget, TargetChanged
from wimm.service.executor import PlanExecutor
from wimm.service.executor_disk_fs import check_disk_fs
from wimm.service.fs_controls import CommandResult

DELETE = ActionKind.DEVDIR_DELETE
CACHE_ENV_LOWER = {name.lower() for name in CACHE_ENV_VARS}


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


def delete_devdir(*, rig: FsRig, folder: Path) -> StepStatus:
    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    return outcomes[0].status


# --- DEVDIR_DELETE ---------------------------------------------------------------


def test_devdir_delete_removes_the_dependency_folder_and_keeps_the_project(rig: FsRig) -> None:
    folder = make_project(root=rig.root)

    outcomes = rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert outcomes[0].freed_bytes is not None and outcomes[0].freed_bytes >= 16384
    assert not folder.exists()
    assert (folder.parent / "src" / "app.js").read_text(encoding="utf-8") == "x"


def test_devdir_delete_also_removes_a_venv(rig: FsRig) -> None:
    folder = make_project(root=rig.root, folder=".venv")
    (folder / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE
    assert not folder.exists()


def make_rust_project(*, rig: FsRig) -> Path:
    """A project with an old `Cargo.toml` and a `target` that carries cargo's cache tag."""
    folder = make_project(root=rig.root, name="crate", folder="target")
    (folder / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    cargo = folder.parent / "Cargo.toml"
    cargo.write_text("[package]\n", encoding="utf-8")
    age(path=cargo, mtime=OLD)
    return folder


def test_devdir_with_its_marker_and_second_signal_is_deleted(rig: FsRig) -> None:
    folder = make_rust_project(rig=rig)

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE
    assert not folder.exists()
    assert (folder.parent / "Cargo.toml").exists()


def test_devdir_without_its_marker_is_refused(rig: FsRig) -> None:
    folder = make_rust_project(rig=rig)
    plan = dir_plan(kind=DELETE, path=folder)
    (folder.parent / "Cargo.toml").unlink()

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=plan)
    assert (folder / "pkg" / "lib" / "util.js").exists()


def test_devdir_that_lost_its_second_signal_is_refused(rig: FsRig) -> None:
    folder = make_rust_project(rig=rig)
    plan = dir_plan(kind=DELETE, path=folder)
    (folder / "CACHEDIR.TAG").unlink()

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=plan)
    assert (folder / "top.txt").exists()


def test_a_venv_without_pyvenv_cfg_is_refused(rig: FsRig) -> None:
    folder = make_project(root=rig.root, folder=".venv")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()


def test_a_project_directly_in_the_home_is_refused(rig: FsRig) -> None:
    rig.control = replace(rig.control, roots=(rig.home,))
    folder = rig.home / "node_modules"
    folder.mkdir()
    (folder / "top.txt").write_text("z", encoding="utf-8")
    age(path=rig.home, mtime=OLD)

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()


def test_a_folder_outside_every_root_is_refused_and_survives(rig: FsRig, tmp_path: Path) -> None:
    folder = make_project(root=rig.home / "elsewhere")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert (folder / "top.txt").exists()

    inside = make_project(root=rig.root)
    assert delete_devdir(rig=rig, folder=inside) is StepStatus.DONE


def test_a_root_whose_real_path_leaves_the_home_is_not_a_root(rig: FsRig, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    folder = make_project(root=outside)
    link = rig.home / "link"
    link.symlink_to(outside)
    rig.control = replace(rig.control, roots=(link,))

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=DELETE, path=folder))
    assert folder.exists()

    rig.control = replace(rig.control, roots=(rig.root,))
    inside = make_project(root=rig.root)
    assert delete_devdir(rig=rig, folder=inside) is StepStatus.DONE


def test_a_symlink_in_place_of_the_folder_is_refused_and_its_target_survives(
    rig: FsRig, tmp_path: Path
) -> None:
    folder = make_project(root=rig.root)
    plan = dir_plan(kind=DELETE, path=folder)
    victim = rig.root / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    shutil.rmtree(folder)
    folder.symlink_to(victim)

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=plan)

    assert folder.is_symlink()
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_a_symlink_inside_the_folder_is_unlinked_not_followed(rig: FsRig) -> None:
    folder = make_project(root=rig.root)
    victim = rig.root / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    (folder / "pkg" / "escape").symlink_to(victim)

    assert delete_devdir(rig=rig, folder=folder) is StepStatus.DONE

    assert not folder.exists()
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep"


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


# --- CACHE_CLEAN -----------------------------------------------------------------

CLEAN = ActionKind.CACHE_CLEAN


def cache_argv(*, relative: str, folder: Path) -> tuple[str, ...]:
    """The command that must run for each cache, aimed at the planned folder."""
    return {
        ".cache/uv": ("uv", "cache", "prune", "--cache-dir", str(folder)),
        ".npm/_cacache": ("npm", "cache", "clean", "--force", "--cache", str(folder.parent)),
        ".cache/pip": ("pip", "--cache-dir", str(folder), "cache", "purge"),
    }[relative]


@pytest.mark.parametrize("relative", [".cache/uv", ".npm/_cacache", ".cache/pip"])
def test_a_cache_is_cleaned_with_its_exact_command(rig: FsRig, relative: str) -> None:
    folder = make_cache(home=rig.home, relative=relative)

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert rig.runner.calls == [cache_argv(relative=relative, folder=folder)]
    assert (folder / "a.bin").exists()


@pytest.mark.parametrize("variable", ["UV_CACHE_DIR", "PIP_CACHE_DIR", "npm_config_cache"])
def test_a_cache_command_runs_without_the_cache_variables_of_the_environment(
    rig: FsRig, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    monkeypatch.setenv(variable, "/elsewhere")
    monkeypatch.setenv(variable.upper(), "/elsewhere")
    monkeypatch.setenv("WIMM_KEPT", "yes")

    rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    (env,) = rig.runner.envs
    assert env is not None
    assert not [name for name in env if name.lower() in CACHE_ENV_LOWER]
    assert env["WIMM_KEPT"] == "yes"


def test_a_cache_in_a_home_behind_a_symlink_is_cleaned(rig: FsRig, tmp_path: Path) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    link = tmp_path / "home-link"
    link.symlink_to(rig.home)
    rig.control = replace(rig.control, home=link)

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert rig.runner.calls == [cache_argv(relative=".cache/uv", folder=folder)]


def test_pip_without_the_tool_on_path_empties_the_folder_instead(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home", which=None)
    folder = make_cache(home=rig.home, relative=".cache/pip")

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert rig.runner.calls == []
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_thumbnails_are_emptied_without_running_a_command(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/thumbnails")

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert outcomes[0].status is StepStatus.DONE
    assert outcomes[0].freed_bytes is not None and outcomes[0].freed_bytes >= 8192
    assert rig.runner.calls == []
    assert folder.is_dir() and list(folder.iterdir()) == []


def test_a_failing_command_fails_the_step_with_its_exit_code(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    rig.runner.result = CommandResult(returncode=2, output="boom")

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert outcomes[0].status is StepStatus.FAILED
    assert "code 2" in (outcomes[0].message or "") and "boom" in (outcomes[0].message or "")


def test_a_command_that_times_out_fails_the_step(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".npm/_cacache")
    rig.runner.error = ControlFailed("npm did not finish within 300 s")

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert outcomes[0].status is StepStatus.FAILED
    assert "did not finish" in (outcomes[0].message or "")
    assert rig.runner.timeouts == [CACHE_COMMAND_TIMEOUT_S]


def test_a_cache_folder_replaced_by_a_symlink_is_refused_and_no_command_runs(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    plan = dir_plan(kind=CLEAN, path=folder)
    moved = rig.home / "moved"
    folder.rename(moved)
    folder.symlink_to(moved)

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=plan)
    assert rig.runner.calls == []

    folder.unlink()
    moved.rename(folder)
    fresh = dir_plan(kind=CLEAN, path=folder)
    assert rig.executor().execute(plan=fresh)[0].status is StepStatus.DONE
    assert rig.runner.calls == [cache_argv(relative=".cache/uv", folder=folder)]


def test_a_cache_with_a_changed_inode_is_refused(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    real = fingerprint_of(path=folder)
    forged = DirFingerprint(realpath=real.realpath, st_ino=real.st_ino + 1, st_dev=real.st_dev)

    with pytest.raises(TargetChanged):
        rig.executor().execute(plan=dir_plan(kind=CLEAN, fingerprint=forged))
    assert rig.runner.calls == []


def test_a_cache_path_outside_the_home_is_refused(
    rig: FsRig, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("decoy") / ".cache" / "uv"
    (outside / "sub").mkdir(parents=True)
    (outside / "sub" / "keep.bin").write_bytes(b"k")

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=CLEAN, path=outside))
    assert (outside / "sub" / "keep.bin").exists()
    assert rig.runner.calls == []


def test_a_cache_action_cannot_target_the_trash(rig: FsRig) -> None:
    trash = make_trash(home=rig.home)

    with pytest.raises(ProtectedTarget):
        check_disk_fs(
            step=dir_plan(kind=CLEAN, path=trash).steps[0],
            control=rig.control,
        )
    assert (trash / "files" / "y.txt").exists()


# --- TRASH_EMPTY -----------------------------------------------------------------

EMPTY = ActionKind.TRASH_EMPTY


def test_trash_empty_removes_files_and_info_but_keeps_the_folders(rig: FsRig) -> None:
    trash = make_trash(home=rig.home)

    outcomes = rig.executor().execute(plan=dir_plan(kind=EMPTY, path=trash))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert outcomes[0].freed_bytes is not None and outcomes[0].freed_bytes >= 4096
    assert (trash / "files").is_dir() and list((trash / "files").iterdir()) == []
    assert (trash / "info").is_dir() and list((trash / "info").iterdir()) == []
    assert (trash / "directorysizes").exists()


def test_a_decoy_trash_outside_the_tmpdir_stays_intact(
    rig: FsRig, tmp_path_factory: pytest.TempPathFactory
) -> None:
    decoy = make_trash(home=tmp_path_factory.mktemp("decoy"))
    real = make_trash(home=rig.home)

    with pytest.raises(ProtectedTarget):
        rig.executor().execute(plan=dir_plan(kind=EMPTY, path=decoy))
    assert (decoy / "files" / "y.txt").exists()
    assert (decoy / "info" / "y.txt.trashinfo").exists()
    assert (real / "files" / "y.txt").exists()

    assert rig.executor().execute(plan=dir_plan(kind=EMPTY, path=real))[0].status is StepStatus.DONE
    assert (decoy / "files" / "y.txt").exists()


def test_a_trash_files_symlink_is_not_followed(rig: FsRig, tmp_path: Path) -> None:
    trash = make_trash(home=rig.home)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    plan = dir_plan(kind=EMPTY, path=trash)
    shutil.rmtree(trash / "files")
    (trash / "files").symlink_to(victim)

    outcomes = rig.executor().execute(plan=plan)

    assert outcomes[0].status is StepStatus.FAILED
    assert (victim / "precious.txt").read_text(encoding="utf-8") == "keep"
    assert not (trash / "info" / "y.txt.trashinfo").exists()


def test_an_already_empty_trash_is_already_gone(rig: FsRig) -> None:
    trash = make_trash(home=rig.home)
    plan = dir_plan(kind=EMPTY, path=trash)
    assert rig.executor().execute(plan=plan)[0].status is StepStatus.DONE

    assert rig.executor().execute(plan=plan)[0].status is StepStatus.ALREADY_GONE
    assert os.path.isdir(trash / "files")
