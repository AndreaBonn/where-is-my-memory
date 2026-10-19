from dataclasses import replace
from pathlib import Path

import pytest

from tests.service.executor_disk_fs_helpers import CLEAN
from tests.service.fs_fakes import (
    FsRig,
    build_rig,
    dir_plan,
    fingerprint_of,
    make_cache,
    make_trash,
)
from wimm.core.constants import CACHE_COMMAND_TIMEOUT_S
from wimm.model.actions import DirFingerprint
from wimm.model.enums import ActionKind
from wimm.service.control_protocols import StepStatus
from wimm.service.errors import (
    ControlFailed,
    ProtectedTarget,
    TargetChanged,
)
from wimm.service.executor_disk_fs import check_disk_fs
from wimm.service.fs_controls import CommandResult


@pytest.fixture
def rig(tmp_path: Path) -> FsRig:
    return build_rig(home=tmp_path / "home")


def cache_argv(*, relative: str, folder: Path) -> tuple[str, ...]:
    """The command that must run for each cache, aimed at the planned folder."""
    return {
        ".cache/uv": ("/usr/bin/uv", "cache", "prune", "--cache-dir", str(folder)),
        ".npm/_cacache": (
            "/usr/bin/npm",
            *("cache", "clean", "--force", "--cache", str(folder.parent)),
        ),
        ".cache/pip": ("/usr/bin/pip", "--cache-dir", str(folder), "cache", "purge"),
    }[relative]


@pytest.mark.parametrize("relative", [".cache/uv", ".npm/_cacache", ".cache/pip"])
def test_a_cache_is_cleaned_with_its_exact_command(rig: FsRig, relative: str) -> None:
    folder = make_cache(home=rig.home, relative=relative)

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert rig.runner.calls == [cache_argv(relative=relative, folder=folder)]
    assert (folder / "a.bin").exists()


@pytest.mark.parametrize("variable", ["UV_CACHE_DIR", "PIP_CACHE_DIR", "npm_config_cache"])
def test_a_cache_command_runs_with_the_allowlisted_environment_only(
    rig: FsRig, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    monkeypatch.setenv(variable, "/elsewhere")
    monkeypatch.setenv("WIMM_STRANGER", "yes")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", str(rig.home))
    monkeypatch.setenv("LANG", "C.UTF-8")

    rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    (env,) = rig.runner.envs
    assert env == {"PATH": "/usr/bin", "HOME": str(rig.home), "LANG": "C.UTF-8"}


def test_a_cache_in_a_home_behind_a_symlink_is_cleaned(rig: FsRig, tmp_path: Path) -> None:
    folder = make_cache(home=rig.home, relative=".cache/uv")
    link = tmp_path / "home-link"
    link.symlink_to(rig.home)
    rig.control = replace(rig.control, home=link)

    outcomes = rig.executor().execute(plan=dir_plan(kind=CLEAN, path=folder))

    assert [o.status for o in outcomes] == [StepStatus.DONE]
    assert rig.runner.calls == [cache_argv(relative=".cache/uv", folder=folder)]


def test_pip_without_the_tool_on_path_empties_the_folder_instead(tmp_path: Path) -> None:
    rig = build_rig(home=tmp_path / "home", missing=("pip",))
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


def test_a_trash_action_cannot_target_a_cache(rig: FsRig) -> None:
    folder = make_cache(home=rig.home, relative=".cache/thumbnails")

    with pytest.raises(ProtectedTarget):
        check_disk_fs(
            step=dir_plan(kind=ActionKind.TRASH_EMPTY, path=folder).steps[0], control=rig.control
        )
    assert (folder / "a.bin").exists() and (folder / "sub" / "b.bin").exists()
    assert rig.runner.calls == []
